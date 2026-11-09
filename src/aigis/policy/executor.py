"""SandboxedToolExecutor — the concrete ``ToolExecutor``
(``agent/executor.py``'s protocol) that Phase 2's ``AgentRuntime`` was built
to accept without modification.

Wires the two Phase 3 pieces together in the only order the project's
thesis allows: PolicyEngine.evaluate() runs first and can short-circuit
before the Sandbox ever sees the request (a DENY/REQUIRE_HUMAN never
touches the filesystem or a subprocess); only an ALLOW reaches the Sandbox.
The result -- whichever branch it came from -- is translated into an
``ExecutionResult`` carrying the ``PolicyDecision`` as part of the evidence,
per ARCHITECTURE.md section 10 ("la autorización [es] parte de la
evidencia").

``run_tests``/``run_lint`` (P0 D1) run a fixed profile from ``policy.yaml``.
The agent gets back a structured, truncated summary -- counts, failing node
ids, assertion messages, lint violations -- never the raw tool output. The
pytest report is written to a temp dir outside the workspace and removed
right after. The caches these tools leave in the workspace (.pytest_cache,
__pycache__, .ruff_cache) are excluded from observed changes by the same
list ``changed_paths()`` uses, so running them is never an
untracked_modification.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from aigis.agent.executor import ExecutionResult
from aigis.domain import (
    ExecutionOutcome,
    PolicyDecision,
    PolicyDecisionType,
    ToolName,
    ToolRequest,
)
from aigis.policy.config import CommandProfile
from aigis.policy.engine import PolicyEngine
from aigis.sandbox.base import CommandResult, Sandbox

# Fixed truncation limits for what goes back to the model.
MAX_FAILURES = 20
MAX_MESSAGE_CHARS = 500
MAX_VIOLATIONS = 50
_REPORT_FILE = "run-tests-report.json"
_CONTAINER_WORKDIR = "/workspace/"  # DockerSandbox's mount point


class SandboxedToolExecutor:
    def __init__(
        self, policy_engine: PolicyEngine, sandbox: Sandbox, *, command_timeout_seconds: int = 60
    ) -> None:
        self.policy_engine = policy_engine
        self.sandbox = sandbox
        self.command_timeout_seconds = command_timeout_seconds

    def execute(self, tool_request: ToolRequest) -> ExecutionResult:
        decision = self.policy_engine.evaluate(tool_request)
        if decision.decision != PolicyDecisionType.ALLOW:
            return ExecutionResult(
                outcome=ExecutionOutcome.POLICY_BLOCKED,
                error=f"{decision.decision.value} ({decision.policy_id}): {decision.reason}",
                policy_decision=decision,
            )

        try:
            return self._run_in_sandbox(tool_request, decision)
        except (OSError, ValueError) as exc:
            # A tool-level failure (patch didn't apply, file missing) is
            # evidence, not a crash -- the agent gets a FAILED result back
            # and can try again, same as any other failed attempt.
            return ExecutionResult(
                outcome=ExecutionOutcome.FAILED, error=str(exc), policy_decision=decision
            )

    def _run_in_sandbox(
        self, tool_request: ToolRequest, decision: PolicyDecision
    ) -> ExecutionResult:
        if tool_request.tool is ToolName.READ_FILE:
            content = self.sandbox.read_file(tool_request.path)
            return ExecutionResult(
                outcome=ExecutionOutcome.COMPLETED, output=content, policy_decision=decision
            )

        if tool_request.tool is ToolName.PATCH_FILE:
            changed_path = self._apply_patch(tool_request)
            return ExecutionResult(
                outcome=ExecutionOutcome.COMPLETED,
                output=f"patched {changed_path}",
                policy_decision=decision,
                changed_path=changed_path,
            )

        if tool_request.tool is ToolName.RUN_TESTS:
            return self._run_tests(tool_request, decision)

        if tool_request.tool is ToolName.RUN_LINT:
            return self._run_lint(decision)

        if tool_request.tool is ToolName.RUN_COMMAND:
            result = self.sandbox.run_command(
                tool_request.executable,
                tool_request.args,
                timeout_seconds=self.command_timeout_seconds,
            )
            if result.timed_out:
                outcome = ExecutionOutcome.TIMEOUT
            elif result.exit_code == 0:
                outcome = ExecutionOutcome.COMPLETED
            else:
                outcome = ExecutionOutcome.FAILED
            return ExecutionResult(
                outcome=outcome,
                output=result.stdout,
                error=None if outcome == ExecutionOutcome.COMPLETED else result.stderr,
                policy_decision=decision,
            )

        raise TypeError(f"unhandled tool: {tool_request.tool!r}")  # pragma: no cover

    def _profile(self, profile_id: str) -> CommandProfile:
        profile = self.policy_engine.config.profile(profile_id)
        if profile is None:  # the Policy Engine DENYs this first (PROF-001)
            raise ValueError(f"no '{profile_id}' profile in the policy")
        return profile

    def _run_tests(self, tool_request: ToolRequest, decision: PolicyDecision) -> ExecutionResult:
        profile = self._profile("run_tests")
        target = tool_request.path or profile.default_target
        report_dir = Path(tempfile.mkdtemp(prefix="aigis-run-tests-"))
        report_file = report_dir / _REPORT_FILE
        try:
            result = self.sandbox.run_command(
                profile.executable,
                [
                    *([target] if target else []),
                    *profile.argv,
                    f"--json-report-file={report_file}",
                ],
                timeout_seconds=profile.timeout_seconds,
            )
            report = _load_json_object(report_file)
        finally:
            shutil.rmtree(report_dir, ignore_errors=True)

        if result.timed_out:
            return ExecutionResult(
                outcome=ExecutionOutcome.TIMEOUT,
                error=f"run_tests timed out after {profile.timeout_seconds}s",
                policy_decision=decision,
            )
        if report is None:
            return ExecutionResult(
                outcome=ExecutionOutcome.FAILED,
                error=_dump(
                    {
                        "error": "pytest produced no report",
                        "exit_code": result.exit_code,
                        "stderr": _truncate(result.stderr),
                    }
                ),
                policy_decision=decision,
            )
        summary = summarize_pytest_report(report, exit_code=result.exit_code, target=target)
        return ExecutionResult(
            outcome=ExecutionOutcome.COMPLETED
            if result.exit_code == 0
            else ExecutionOutcome.FAILED,
            output=_dump(summary),
            policy_decision=decision,
        )

    def _run_lint(self, decision: PolicyDecision) -> ExecutionResult:
        profile = self._profile("run_lint")
        result = self.sandbox.run_command(
            profile.executable, list(profile.argv), timeout_seconds=profile.timeout_seconds
        )
        if result.timed_out:
            return ExecutionResult(
                outcome=ExecutionOutcome.TIMEOUT,
                error=f"run_lint timed out after {profile.timeout_seconds}s",
                policy_decision=decision,
            )
        summary = summarize_ruff_output(result, workdir=getattr(self.sandbox, "workdir", None))
        if "error" in summary:
            return ExecutionResult(
                outcome=ExecutionOutcome.FAILED, error=_dump(summary), policy_decision=decision
            )
        return ExecutionResult(
            outcome=ExecutionOutcome.COMPLETED
            if summary["violation_count"] == 0
            else ExecutionOutcome.FAILED,
            output=_dump(summary),
            policy_decision=decision,
        )

    def _apply_patch(self, tool_request: ToolRequest) -> str:
        path = tool_request.path
        current = self.sandbox.read_file(path)
        occurrences = current.count(tool_request.old_str)
        if occurrences == 0:
            raise ValueError(f"old_str not found in {path}")
        if occurrences > 1:
            raise ValueError(f"old_str is not unique in {path} ({occurrences} occurrences)")
        updated = current.replace(tool_request.old_str, tool_request.new_str, 1)
        self.sandbox.write_file(path, updated)
        return path


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _truncate(text: str | None, limit: int = MAX_MESSAGE_CHARS) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"... [truncated, {len(text)} chars]"


def _load_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _failure_message(test: dict[str, Any]) -> str:
    for phase in ("setup", "call", "teardown"):
        stage = test.get(phase)
        if not isinstance(stage, dict) or stage.get("outcome") == "passed":
            continue
        crash = stage.get("crash")
        if isinstance(crash, dict) and crash.get("message"):
            return str(crash["message"])
        if stage.get("longrepr"):
            return str(stage["longrepr"])
    return ""


def summarize_pytest_report(
    report: dict[str, Any], *, exit_code: int, target: str | None
) -> dict[str, Any]:
    """What run_tests returns to the model: counts, the failing node ids
    and each one's assertion message, with fixed truncation limits."""
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}

    def count(key: str) -> int:
        value = summary.get(key, 0)
        return value if isinstance(value, int) else 0

    tests = report.get("tests") if isinstance(report.get("tests"), list) else []
    failing = [t for t in tests if isinstance(t, dict) and t.get("outcome") in ("failed", "error")]
    return {
        "target": target,
        "exit_code": exit_code,
        "passed": count("passed"),
        "failed": count("failed"),
        "errors": count("error"),
        "skipped": count("skipped"),
        "xfailed": count("xfailed"),
        "xpassed": count("xpassed"),
        "failures": [
            {"nodeid": str(t.get("nodeid")), "message": _truncate(_failure_message(t))}
            for t in failing[:MAX_FAILURES]
        ],
        "failures_omitted": max(0, len(failing) - MAX_FAILURES),
    }


def _relative(filename: Any, workdir: Path | None) -> str:
    name = str(filename)
    if workdir is not None:
        try:
            return Path(name).resolve().relative_to(Path(workdir).resolve()).as_posix()
        except (OSError, ValueError):
            pass
    if name.startswith(_CONTAINER_WORKDIR):
        return PurePosixPath(name[len(_CONTAINER_WORKDIR) :]).as_posix()
    return name


def summarize_ruff_output(result: CommandResult, *, workdir: Path | None) -> dict[str, Any]:
    """What run_lint returns to the model: the violations as data
    (path, line, code, message), with fixed truncation limits."""
    if result.exit_code not in (0, 1):
        return {
            "error": "ruff exited abnormally",
            "exit_code": result.exit_code,
            "stderr": _truncate(result.stderr),
        }
    try:
        violations = json.loads(result.stdout) if result.stdout else []
    except json.JSONDecodeError:
        violations = None
    if not isinstance(violations, list):
        return {"error": "unparseable ruff output", "exit_code": result.exit_code}
    items = [v for v in violations if isinstance(v, dict)]
    return {
        "violation_count": len(items),
        "violations": [
            {
                "path": _relative(v.get("filename"), workdir),
                "row": (v.get("location") or {}).get("row"),
                "code": v.get("code"),
                "message": _truncate(str(v.get("message", "")), 200),
            }
            for v in items[:MAX_VIOLATIONS]
        ],
        "violations_omitted": max(0, len(items) - MAX_VIOLATIONS),
    }


__all__ = ["SandboxedToolExecutor", "summarize_pytest_report", "summarize_ruff_output"]
