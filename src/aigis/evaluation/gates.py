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
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from aigis.domain.enums import GateType
from aigis.domain.quality_gate import GateResult
from aigis.sandbox.base import CommandResult, Sandbox

_PYTEST_REPORT_FILE = "pytest-report.json"

# Exit codes that mean "the tool could not run", never "the code under test
# failed" (P0 D3). 126/127: not executable / not found (what LocalCowSandbox
# and a shell return). pytest 4: usage error -- e.g. the json-report plugin
# is missing, so --json-report is an unrecognized argument.
_NOT_RUNNABLE = {126, 127}
_PYTEST_USAGE_ERROR = 4

# Test outcomes that are neither a pass nor a failure: a test that ends in
# one of these proved nothing. The code under test can produce all three at
# run time (pytest.skip()/pytest.xfail() called from src/), so they only
# count when the base already produced the same outcome.
_NON_VERDICT_OUTCOMES = ("skipped", "xfailed", "xpassed")

# What ruff lints by default. An agent-changed file with another suffix is
# not handed to ruff explicitly (ruff would try to parse it as Python).
_LINTABLE_SUFFIXES = (".py", ".pyi", ".ipynb")


@dataclass(frozen=True)
class GateContext:
    """Per-run inputs a gate needs beyond the sandbox. Built by the
    orchestrator for each run, never stored on the gate instance (the
    default gates are module-level singletons shared across runs).

    - ``baseline``: for pytest, ``{nodeid: outcome}`` of the same tests run
      on a clean copy of the base repo before the agent's turn.
    - ``baseline_error``: why that baseline could not be taken. The gate
      then has no verdict (``infrastructure_error``), never a PASS.
    - ``agent_changed_files``: observed changes outside ``protected_paths``
      (relative paths). RuffGate lints these with ``--ignore-noqa``.
    """

    baseline: Mapping[str, str] | None = None
    baseline_error: str | None = None
    agent_changed_files: tuple[str, ...] = ()


class QualityGate(Protocol):
    gate_name: str
    gate_type: GateType

    def run(
        self,
        sandbox: Sandbox,
        *,
        report_dir: Path | None = None,
        context: GateContext | None = None,
    ) -> GateResult: ...


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

    No silent pass (D3 hardening): exit code 0 is not enough, because the
    code under test can call ``pytest.skip()``/``pytest.xfail()`` and pytest
    still exits 0. A PASS also needs at least one passed test, zero failed,
    zero errors, and every test whose outcome is skipped/xfailed/xpassed
    must have had that same outcome on the base (``context.baseline``, taken
    by :meth:`collect_baseline` before the agent's turn). A base test that
    is missing from the run (e.g. its module skipped at import) counts too.
    Each broken rule is a ``rule_violations`` entry -> FAIL
    (``gate_outcome_changed`` / ``no_test_passed``). Without a context there
    is no baseline, so any skip/xfail/xpass FAILs. This closes the cheap
    cases, not the general one: code that patches pytest itself at import
    time is still the documented limit above.
    """

    gate_name = "pytest"
    gate_type = GateType.TEST

    def __init__(self, *, args: list[str] | None = None, timeout_seconds: int = 120) -> None:
        self.args = args if args is not None else ["tests/"]
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        sandbox: Sandbox,
        *,
        report_dir: Path | None = None,
        context: GateContext | None = None,
    ) -> GateResult:
        if context is not None and context.baseline_error is not None:
            # No baseline, no way to tell a legitimate skip from one the
            # agent's code produced: no verdict (NEEDS_HUMAN downstream).
            return self._result(
                False,
                {"error": "pytest baseline unavailable"},
                infrastructure_error=f"pytest baseline unavailable: {context.baseline_error}",
            )
        baseline = context.baseline if context is not None else None
        own_dir = report_dir is None
        if report_dir is None:
            report_dir = Path(tempfile.mkdtemp(prefix="aigis-pytest-report-"))
        directory = report_dir
        try:
            return self._run(sandbox, directory / _PYTEST_REPORT_FILE, baseline)
        finally:
            if own_dir:
                shutil.rmtree(directory, ignore_errors=True)

    def collect_baseline(self, sandbox: Sandbox) -> GateContext:
        """Runs the same tests in ``sandbox`` -- a clean copy of the base
        repo that the agent never touches -- and returns their outcomes as
        a :class:`GateContext`. The report goes to a temp dir outside the
        sandbox, removed right after. Never raises: a run that leaves no
        usable report becomes ``baseline_error``.
        """
        directory = Path(tempfile.mkdtemp(prefix="aigis-pytest-baseline-"))
        report_file = directory / _PYTEST_REPORT_FILE
        try:
            result = self._invoke(sandbox, report_file)
            if result.timed_out:
                return GateContext(baseline_error="baseline run timed out")
            report = _load_report(report_file)
            if report is None:
                return GateContext(
                    baseline_error=f"pytest exited {result.exit_code} without a usable report"
                )
            return GateContext(baseline=_outcomes(report))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def _invoke(self, sandbox: Sandbox, report_file: Path) -> CommandResult:
        report_file.unlink(missing_ok=True)
        return sandbox.run_command(
            "pytest",
            [
                *self.args,
                "-q",
                "--json-report",
                f"--json-report-file={report_file}",
            ],
            timeout_seconds=self.timeout_seconds,
        )

    def _run(
        self, sandbox: Sandbox, report_file: Path, baseline: Mapping[str, str] | None
    ) -> GateResult:
        result = self._invoke(sandbox, report_file)

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
        if not isinstance(summary, dict):
            summary = {}
        # Both exit codes must agree: the report's own and the process's.
        exits_ok = report.get("exitcode") == 0 and result.exit_code == 0
        no_failures = _count(summary, "failed") == 0 and _count(summary, "error") == 0
        violations = _outcome_violations(report, summary, baseline)
        duration = report.get("duration")
        return self._result(
            exits_ok and no_failures and not violations,
            {"report": report},
            duration_seconds=duration if isinstance(duration, (int, float)) else None,
            rule_violations=violations,
        )

    def _result(
        self,
        passed: bool,
        details: dict[str, Any],
        *,
        infrastructure_error: str | None = None,
        duration_seconds: float | None = None,
        rule_violations: list[str] | None = None,
    ) -> GateResult:
        return GateResult(
            gate_name=self.gate_name,
            gate_type=self.gate_type,
            passed=passed,
            details=details,
            duration_seconds=duration_seconds,
            infrastructure_error=infrastructure_error,
            rule_violations=rule_violations or [],
        )


def _count(summary: Mapping[str, Any], key: str) -> int:
    value = summary.get(key, 0)
    return value if isinstance(value, int) else 0


def _load_report(report_file: Path) -> dict[str, Any] | None:
    if not report_file.is_file():
        return None
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return report if isinstance(report, dict) else None


def _outcomes(report: Mapping[str, Any]) -> dict[str, str]:
    tests = report.get("tests")
    if not isinstance(tests, list):
        return {}
    return {
        str(test["nodeid"]): str(test.get("outcome"))
        for test in tests
        if isinstance(test, dict) and "nodeid" in test
    }


def _outcome_violations(
    report: Mapping[str, Any],
    summary: Mapping[str, Any],
    baseline: Mapping[str, str] | None,
) -> list[str]:
    """The no-silent-pass rules (D3 hardening). ``baseline`` None means no
    baseline was taken: every skip/xfail/xpass is then a violation.
    """
    violations: list[str] = []
    if _count(summary, "passed") < 1:
        violations.append("no_test_passed")

    outcomes = _outcomes(report)
    reference = baseline or {}
    for nodeid, outcome in sorted(outcomes.items()):
        if outcome in _NON_VERDICT_OUTCOMES and reference.get(nodeid) != outcome:
            before = reference.get(nodeid, "absent")
            violations.append(f"gate_outcome_changed: {nodeid} ({before} -> {outcome})")
    for nodeid in sorted(set(reference) - set(outcomes)):
        violations.append(f"gate_outcome_changed: {nodeid} ({reference[nodeid]} -> absent)")

    # A summary that counts more non-verdict outcomes than the test list
    # shows cannot be checked against the baseline: fail closed.
    listed = sum(1 for outcome in outcomes.values() if outcome in _NON_VERDICT_OUTCOMES)
    counted = sum(_count(summary, key) for key in _NON_VERDICT_OUTCOMES)
    if counted > listed:
        violations.append(
            f"gate_outcome_changed: {counted - listed} non-verdict test(s) missing from the report"
        )
    return violations


class RuffGate:
    """Runs ``ruff check`` inside the sandbox and grades it from ruff's own
    structured JSON output (``--output-format json``), never from the
    human-readable text format.

    No silent pass (D3 hardening): a ``# noqa`` or a file-level
    ``# ruff: noqa`` is just text in the file, so the agent could silence a
    real violation in the code it wrote. The files the agent changed
    (``context.agent_changed_files``, lintable suffixes only, still present
    in the evaluation workspace) are linted with ``--ignore-noqa``; the
    rest of the repo gets the normal check, so a ``noqa`` already in the
    base keeps working there. Consequence, on purpose: in a file the agent
    touched, a violation the base had silenced with ``noqa`` is reported
    too.
    """

    gate_name = "ruff"
    gate_type = GateType.LINT

    def __init__(self, *, args: list[str] | None = None, timeout_seconds: int = 60) -> None:
        self.args = args if args is not None else ["."]
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        sandbox: Sandbox,
        *,
        report_dir: Path | None = None,
        context: GateContext | None = None,
    ) -> GateResult:
        # report_dir is unused: ruff's report is its stdout, and ruff never
        # executes the code it lints. Accepted for the QualityGate protocol.
        changed = _lintable_present(sandbox, context.agent_changed_files if context else ())
        normal = self._check(sandbox, ["check", *self.args, "--output-format", "json"])
        if not isinstance(normal, list):
            return normal
        if not changed:
            return self._graded(normal, [])
        strict = self._check(
            sandbox,
            [
                "check",
                "--ignore-noqa",
                "--force-exclude",
                "--output-format",
                "json",
                # "./" so that no path can be read as an option.
                *(f"./{path}" for path in changed),
            ],
        )
        if not isinstance(strict, list):
            return strict
        # For a changed file the --ignore-noqa run reports everything the
        # normal run does and more, so the union (deduplicated) is exact.
        # No path matching on ruff's absolute filenames is needed.
        return self._graded(_dedupe([*normal, *strict]), changed)

    def _graded(self, violations: list[dict[str, Any]], changed: list[str]) -> GateResult:
        report = {
            "violations": violations,
            "violation_count": len(violations),
            "ignore_noqa_files": changed,
        }
        return GateResult(
            gate_name=self.gate_name,
            gate_type=self.gate_type,
            passed=len(violations) == 0,
            details={"report": report},
        )

    def _check(self, sandbox: Sandbox, args: list[str]) -> list[dict[str, Any]] | GateResult:
        """One ruff invocation: its violations, or the GateResult that ends
        the gate (timeout, infrastructure error, unparseable output)."""
        result = sandbox.run_command("ruff", args, timeout_seconds=self.timeout_seconds)

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
            violations = json.loads(result.stdout) if result.stdout else []
        except json.JSONDecodeError as exc:
            violations = None
            error = f"unparseable ruff output: {exc}"
        else:
            error = "ruff output is not a list of violations"
        if not isinstance(violations, list):
            return GateResult(
                gate_name=self.gate_name,
                gate_type=self.gate_type,
                passed=False,
                details={"error": error, "stdout": result.stdout},
            )
        return violations


def _lintable_present(sandbox: Sandbox, paths: tuple[str, ...] | list[str]) -> list[str]:
    """Agent-changed files ruff should lint strictly: lintable suffix and
    still a readable file in the evaluation workspace (a deletion is a
    change too, and ruff would report a missing path as a violation).
    """
    present = []
    for path in sorted(set(paths)):
        if not path.endswith(_LINTABLE_SUFFIXES):
            continue
        try:
            sandbox.read_file(path)
        except (OSError, ValueError):
            continue
        present.append(path)
    return present


def _dedupe(violations: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique = []
    for violation in violations:
        key = json.dumps(violation, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(violation)
    return unique


__all__ = ["GateContext", "QualityGate", "PytestGate", "RuffGate"]
