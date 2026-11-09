from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from aigis.domain.enums import GateType
from aigis.domain.quality_gate import GateResult
from aigis.evaluation.gates import _PYTEST_REPORT_FILE, GateContext, PytestGate, RuffGate
from aigis.sandbox.base import REPORT_DIR_TOKEN, CommandResult
from aigis.sandbox.local_cow import LocalCowSandbox


class FakeSandbox:
    """Test double satisfying the Sandbox protocol -- same shape as the one
    in tests/policy/test_executor.py, kept separate since gates only need
    read_file/run_command, not the full lifecycle.
    """

    def __init__(
        self, *, command_result: CommandResult, files: dict[str, str] | None = None
    ) -> None:
        self.command_result = command_result
        self.files = dict(files or {})

    def create(self) -> None:
        pass

    def read_file(self, path: str) -> str:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_file(self, path: str, content: str) -> None:
        self.files[path] = content

    def run_command(
        self, executable: str, args: list[str], *, timeout_seconds: int, report_dir=None
    ) -> CommandResult:
        # Plays pytest-json-report: since P0 D3 the gate reads its report
        # from the --json-report-file path (outside the workspace), never
        # through read_file -- so the fake writes it there, as pytest would.
        for arg in args:
            if arg.startswith("--json-report-file=") and _PYTEST_REPORT_FILE in self.files:
                target = arg.split("=", 1)[1].replace(REPORT_DIR_TOKEN, str(report_dir))
                Path(target).write_text(
                    self.files[_PYTEST_REPORT_FILE], encoding="utf-8"
                )
        return self.command_result

    def collect_diff(self) -> str:
        return ""

    def destroy(self) -> None:
        pass


# --- PytestGate --------------------------------------------------------------


def test_pytest_gate_passes_when_report_says_zero_failed() -> None:
    report = {"exitcode": 0, "duration": 0.42, "summary": {"passed": 3, "failed": 0}}
    sandbox = FakeSandbox(
        command_result=CommandResult(exit_code=0, stdout="3 passed", stderr=""),
        files={_PYTEST_REPORT_FILE: json.dumps(report)},
    )

    result = PytestGate().run(sandbox)

    assert result.gate_name == "pytest"
    assert result.gate_type == GateType.TEST
    assert result.passed is True
    assert result.details["report"]["summary"]["failed"] == 0
    assert result.duration_seconds == 0.42


def test_pytest_gate_fails_when_report_says_tests_failed() -> None:
    report = {"exitcode": 1, "summary": {"passed": 2, "failed": 1}}
    sandbox = FakeSandbox(
        command_result=CommandResult(exit_code=1, stdout="1 failed", stderr=""),
        files={_PYTEST_REPORT_FILE: json.dumps(report)},
    )

    result = PytestGate().run(sandbox)

    assert result.passed is False


def test_pytest_gate_fails_closed_when_report_never_materializes() -> None:
    """A crash before pytest-json-report could write its file is graded as a
    failure, not silently treated as passed just because nothing contradicted
    it -- fail closed (ARCHITECTURE.md section 3.6).
    """
    sandbox = FakeSandbox(
        command_result=CommandResult(exit_code=2, stdout="", stderr="internal error"),
        files={},
    )

    result = PytestGate().run(sandbox)

    assert result.passed is False
    assert "error" in result.details


def test_pytest_gate_timeout_fails_without_looking_for_a_report() -> None:
    sandbox = FakeSandbox(
        command_result=CommandResult(exit_code=-1, stdout="", stderr="", timed_out=True),
        files={_PYTEST_REPORT_FILE: json.dumps({"exitcode": 0, "summary": {"failed": 0}})},
    )

    result = PytestGate().run(sandbox)

    assert result.passed is False
    assert result.details["timed_out"] is True


# --- No silent pass (D3 hardening) ------------------------------------------------


def _report_sandbox(report: dict, exit_code: int = 0) -> FakeSandbox:
    return FakeSandbox(
        command_result=CommandResult(exit_code=exit_code, stdout="", stderr=""),
        files={_PYTEST_REPORT_FILE: json.dumps(report)},
    )


def _skip_report(*, passed: int = 1) -> dict:
    tests = [{"nodeid": "tests/t.py::test_skip", "outcome": "skipped"}]
    tests += [{"nodeid": f"tests/t.py::test_ok{i}", "outcome": "passed"} for i in range(passed)]
    return {"exitcode": 0, "summary": {"passed": passed, "skipped": 1}, "tests": tests}


def test_pytest_gate_zero_passed_tests_is_not_a_pass() -> None:
    result = PytestGate().run(_report_sandbox({"exitcode": 0, "summary": {"total": 0}}))
    assert result.passed is False
    assert result.rule_violations == ["no_test_passed"]


def test_pytest_gate_errors_are_not_a_pass() -> None:
    report = {"exitcode": 0, "summary": {"passed": 1, "error": 1}}
    assert PytestGate().run(_report_sandbox(report)).passed is False


def test_pytest_gate_without_baseline_any_skip_fails() -> None:
    result = PytestGate().run(_report_sandbox(_skip_report()))
    assert result.passed is False
    assert result.rule_violations == [
        "gate_outcome_changed: tests/t.py::test_skip (absent -> skipped)"
    ]


def test_pytest_gate_skip_matching_the_baseline_passes() -> None:
    context = GateContext(
        baseline={"tests/t.py::test_skip": "skipped", "tests/t.py::test_ok0": "failed"}
    )
    result = PytestGate().run(_report_sandbox(_skip_report()), context=context)
    assert result.passed is True
    assert result.rule_violations == []


def test_pytest_gate_baseline_xfail_turned_xpass_fails() -> None:
    report = {
        "exitcode": 0,
        "summary": {"passed": 1, "xpassed": 1},
        "tests": [
            {"nodeid": "tests/t.py::test_ok", "outcome": "passed"},
            {"nodeid": "tests/t.py::test_x", "outcome": "xpassed"},
        ],
    }
    context = GateContext(
        baseline={"tests/t.py::test_ok": "passed", "tests/t.py::test_x": "xfailed"}
    )
    result = PytestGate().run(_report_sandbox(report), context=context)
    assert result.rule_violations == [
        "gate_outcome_changed: tests/t.py::test_x (xfailed -> xpassed)"
    ]


def test_pytest_gate_summary_counting_unlisted_skips_fails_closed() -> None:
    report = {"exitcode": 0, "summary": {"passed": 1, "skipped": 2}, "tests": []}
    result = PytestGate().run(_report_sandbox(report), context=GateContext(baseline={}))
    assert result.passed is False
    assert any("missing from the report" in v for v in result.rule_violations)


def test_pytest_gate_baseline_error_is_infrastructure_error() -> None:
    result = PytestGate().run(
        _report_sandbox(_skip_report()), context=GateContext(baseline_error="pytest exited 127")
    )
    assert result.passed is False
    assert result.infrastructure_error is not None
    assert "baseline unavailable" in result.infrastructure_error


def test_pytest_gate_collect_baseline_without_report_is_an_error() -> None:
    sandbox = FakeSandbox(command_result=CommandResult(exit_code=127, stdout="", stderr=""))
    context = PytestGate().collect_baseline(sandbox)
    assert context.baseline is None
    assert context.baseline_error == "pytest exited 127 without a usable report"


def test_gate_result_rule_violations_never_pass() -> None:
    with pytest.raises(ValueError):
        GateResult(gate_name="pytest", gate_type=GateType.TEST, passed=True, rule_violations=["x"])


# --- RuffGate ------------------------------------------------------------------


def test_ruff_gate_passes_with_no_violations() -> None:
    sandbox = FakeSandbox(command_result=CommandResult(exit_code=0, stdout="[]", stderr=""))

    result = RuffGate().run(sandbox)

    assert result.gate_name == "ruff"
    assert result.gate_type == GateType.LINT
    assert result.passed is True
    assert result.details["report"]["violation_count"] == 0


def test_ruff_gate_fails_with_violations_from_structured_output() -> None:
    violations = [{"code": "F401", "message": "unused import"}]
    sandbox = FakeSandbox(
        command_result=CommandResult(exit_code=1, stdout=json.dumps(violations), stderr="")
    )

    result = RuffGate().run(sandbox)

    assert result.passed is False
    assert result.details["report"]["violation_count"] == 1


def test_ruff_gate_abnormal_exit_code_is_a_tool_error_not_a_lint_failure() -> None:
    sandbox = FakeSandbox(command_result=CommandResult(exit_code=2, stdout="", stderr="boom"))

    result = RuffGate().run(sandbox)

    assert result.passed is False
    assert "error" in result.details


def test_ruff_gate_timeout_fails() -> None:
    sandbox = FakeSandbox(
        command_result=CommandResult(exit_code=-1, stdout="", stderr="", timed_out=True)
    )

    result = RuffGate().run(sandbox)

    assert result.passed is False
    assert result.details["timed_out"] is True


# --- end-to-end against a real sandbox (no mocks) -------------------------------


@pytest.mark.skipif(
    shutil.which("pytest") is None or shutil.which("ruff") is None,
    reason="pytest/ruff must be resolvable on PATH for a subprocess with a restricted env",
)
def test_gates_run_for_real_inside_local_cow_sandbox(tmp_path: Path) -> None:
    repo = tmp_path / "toy-repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")

    sandbox = LocalCowSandbox(repo)
    sandbox.create()
    try:
        pytest_result = PytestGate().run(sandbox)
        ruff_result = RuffGate().run(sandbox)
    finally:
        sandbox.destroy()

    assert pytest_result.passed is True
    assert pytest_result.details["report"]["summary"]["passed"] == 1
    assert ruff_result.passed is True
