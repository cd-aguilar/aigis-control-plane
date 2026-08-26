from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from aigis.domain.enums import GateType
from aigis.evaluation.gates import _PYTEST_REPORT_FILE, PytestGate, RuffGate
from aigis.sandbox.base import CommandResult
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
        self, executable: str, args: list[str], *, timeout_seconds: int
    ) -> CommandResult:
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
