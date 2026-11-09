"""QualityGate — a deterministic pass/fail check run inside the Sandbox.

Per ARCHITECTURE.md section 12: gates are deterministic and rely on
structured output (``pytest-json-report``, ``ruff --output-format json``)
rather than regex over stdout — "evita que un gate supuestamente
determinista dependa de interpretar texto libre." Each gate drives the same
``Sandbox`` protocol ``policy/executor.py`` already uses, so a gate never
sees the host repo directly.

Since P0 D3 the sandbox a gate runs in is in its *evaluation* phase
(``Sandbox.start_evaluation``): the base repo plus the agent's changes
outside ``protected_paths`` -- never the agent's workspace as the agent left
it. Tests and test/lint config always come from the base.

Gates run *after* the agent's turn is over (there is no ``ToolRequest`` /
Policy Engine involvement here — the Control Plane itself is driving the
sandbox at this point, not the agent), so ``pytest``/``ruff`` being on the
command allowlist in ``policy.yaml`` is a coincidence of least-privilege
scoping, not a dependency of this module.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Protocol

from aigis.domain.enums import GateType
from aigis.domain.quality_gate import GateResult
from aigis.sandbox.base import Sandbox

_PYTEST_REPORT_FILE = "pytest-report.json"

# Exit codes that mean "the tool could not run", never "the code under test
# failed" (P0 D3). 126/127: not executable / not found (what LocalCowSandbox
# and a shell return). pytest 4: usage error -- e.g. the json-report plugin
# is missing, so --json-report is an unrecognized argument.
_NOT_RUNNABLE = {126, 127}
_PYTEST_USAGE_ERROR = 4


class QualityGate(Protocol):
    gate_name: str
    gate_type: GateType

    def run(self, sandbox: Sandbox, *, report_dir: Path | None = None) -> GateResult: ...


class PytestGate:
    """Runs ``pytest`` inside the sandbox and grades it from the
    ``pytest-json-report`` output, never from stdout text or the bare exit
    code alone.

    The report is written to ``report_dir`` -- a directory the control
    plane creates, OUTSIDE the evaluation workspace -- and read back from
    there with a plain host read, never through ``sandbox.read_file`` (P0
    D3): a report the agent planted in its workspace is never graded.
    Without ``report_dir`` the gate makes (and removes) its own.

    Limit, not a guarantee: pytest imports the agent's code, so that code
    runs inside the gate process and can still write the report path or
    patch pytest at import time. Closing that needs process isolation
    between the grader and the code it grades (D5 and beyond); see
    docs/SECURITY.md.

    Outcomes, decided by exit code and by whether the report exists, never
    by stdout/stderr text:
    - report present -> graded from the report (PASS or FAIL);
    - no report and exit 126/127 (not found) or 4 (usage error) ->
      ``infrastructure_error`` (NEEDS_HUMAN downstream);
    - no report with any other exit code, or an unparseable report -> FAIL:
      pytest ran, and something in the run (the code under test included)
      got in the way of its own report.
    """

    gate_name = "pytest"
    gate_type = GateType.TEST

    def __init__(self, *, args: list[str] | None = None, timeout_seconds: int = 120) -> None:
        self.args = args if args is not None else ["tests/"]
        self.timeout_seconds = timeout_seconds

    def run(self, sandbox: Sandbox, *, report_dir: Path | None = None) -> GateResult:
        own_dir = report_dir is None
        if report_dir is None:
            report_dir = Path(tempfile.mkdtemp(prefix="aigis-pytest-report-"))
        directory = report_dir
        try:
            return self._run(sandbox, directory / _PYTEST_REPORT_FILE)
        finally:
            if own_dir:
                shutil.rmtree(directory, ignore_errors=True)

    def _run(self, sandbox: Sandbox, report_file: Path) -> GateResult:
        report_file.unlink(missing_ok=True)
        result = sandbox.run_command(
            "pytest",
            [
                *self.args,
                "-q",
                "--json-report",
                f"--json-report-file={report_file}",
            ],
            timeout_seconds=self.timeout_seconds,
        )

        if result.timed_out:
            return self._result(False, {"timed_out": True, "stderr": result.stderr})

        diagnostics = {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        if not report_file.is_file():
            if result.exit_code in _NOT_RUNNABLE or result.exit_code == _PYTEST_USAGE_ERROR:
                return self._result(
                    False,
                    {"error": "pytest could not run", **diagnostics},
                    infrastructure_error=f"pytest exited {result.exit_code} without a report",
                )
            return self._result(
                False, {"error": "pytest-json-report was not produced", **diagnostics}
            )

        try:
            report = json.loads(report_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._result(False, {"error": f"unreadable pytest report: {exc}", **diagnostics})
        if not isinstance(report, dict):
            return self._result(False, {"error": "pytest report is not an object", **diagnostics})

        summary = report.get("summary", {})
        # Both exit codes must agree: the report's own and the process's.
        passed = (
            report.get("exitcode") == 0
            and result.exit_code == 0
            and isinstance(summary, dict)
            and summary.get("failed", 0) == 0
        )
        duration = report.get("duration")
        return self._result(
            passed,
            {"report": report},
            duration_seconds=duration if isinstance(duration, (int, float)) else None,
        )

    def _result(
        self,
        passed: bool,
        details: dict[str, Any],
        *,
        infrastructure_error: str | None = None,
        duration_seconds: float | None = None,
    ) -> GateResult:
        return GateResult(
            gate_name=self.gate_name,
            gate_type=self.gate_type,
            passed=passed,
            details=details,
            duration_seconds=duration_seconds,
            infrastructure_error=infrastructure_error,
        )


class RuffGate:
    """Runs ``ruff check`` inside the sandbox and grades it from ruff's own
    structured JSON output (``--output-format json``), never from the
    human-readable text format.
    """

    gate_name = "ruff"
    gate_type = GateType.LINT

    def __init__(self, *, args: list[str] | None = None, timeout_seconds: int = 60) -> None:
        self.args = args if args is not None else ["."]
        self.timeout_seconds = timeout_seconds

    def run(self, sandbox: Sandbox, *, report_dir: Path | None = None) -> GateResult:
        # report_dir is unused: ruff's report is its stdout, and ruff never
        # executes the code it lints. Accepted for the QualityGate protocol.
        result = sandbox.run_command(
            "ruff",
            ["check", *self.args, "--output-format", "json"],
            timeout_seconds=self.timeout_seconds,
        )

        if result.timed_out:
            return GateResult(
                gate_name=self.gate_name,
                gate_type=self.gate_type,
                passed=False,
                details={"timed_out": True, "stderr": result.stderr},
            )

        # ruff check exits 0 (no violations) or 1 (violations found) as its
        # normal, structured outcomes. Anything else (127 not found, 2 ruff
        # error) means the tool produced no verdict: an infrastructure error
        # (P0 D3), not a lint failure. ruff does not run the linted code,
        # and every ruff config is a protected path, so the agent cannot
        # trigger this from the evaluation workspace.
        if result.exit_code not in (0, 1):
            return GateResult(
                gate_name=self.gate_name,
                gate_type=self.gate_type,
                passed=False,
                details={
                    "error": "ruff exited abnormally",
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                infrastructure_error=f"ruff exited {result.exit_code}",
            )

        try:
            violations: list[dict[str, Any]] = json.loads(result.stdout) if result.stdout else []
        except json.JSONDecodeError as exc:
            return GateResult(
                gate_name=self.gate_name,
                gate_type=self.gate_type,
                passed=False,
                details={"error": f"unparseable ruff output: {exc}", "stdout": result.stdout},
            )
        report = {"violations": violations, "violation_count": len(violations)}

        return GateResult(
            gate_name=self.gate_name,
            gate_type=self.gate_type,
            passed=len(violations) == 0,
            details={"report": report},
        )


__all__ = ["QualityGate", "PytestGate", "RuffGate"]
