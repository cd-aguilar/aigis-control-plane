"""P0 D1: run_tests / run_lint run fixed profiles from policy.yaml.

- The profiles are the same invocation the gates grade with (parity is
  checked by recording the argv both sides actually send to the sandbox).
- A profile is argv, never a shell string.
- What goes back to the model is a structured, truncated summary.
- Running them in the agent's workspace leaves only caches the observed
  changes already ignore: no untracked_modification.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aigis.domain import ExecutionOutcome, TaskContract, ToolName, ToolRequest
from aigis.evaluation.gates import PytestGate, RuffGate
from aigis.policy.config import CommandProfile, PolicyConfig, load_policy_config
from aigis.policy.engine import PolicyEngine
from aigis.policy.executor import (
    MAX_FAILURES,
    MAX_MESSAGE_CHARS,
    SandboxedToolExecutor,
    summarize_pytest_report,
)
from aigis.sandbox.base import CommandResult
from aigis.sandbox.local_cow import LocalCowSandbox


def _contract() -> TaskContract:
    return TaskContract(
        task_id="T-d1",
        description="fix subtract()",
        allowed_paths=["src/"],
        forbidden_paths=["secrets/"],
        success_criteria=["pytest tests/ exits 0"],
        required_gates=["pytest"],
        max_iterations=5,
        max_runtime_seconds=60,
        max_tool_calls=10,
        max_files_changed=2,
    )


class _Recorder:
    """Records every command; plays a successful run with an empty report."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def run_command(self, executable: str, args: list[str], *, timeout_seconds: int):
        self.calls.append((executable, list(args)))
        for arg in args:
            if arg.startswith("--json-report-file="):
                Path(arg.split("=", 1)[1]).write_text(
                    json.dumps({"exitcode": 0, "summary": {"passed": 1}}), encoding="utf-8"
                )
        return CommandResult(exit_code=0, stdout="[]", stderr="")

    def read_file(self, path: str) -> str:
        raise FileNotFoundError(path)


def _without_report_file(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("--json-report-file=")]


def test_run_tests_profile_is_the_pytest_gate_invocation() -> None:
    gate_side, tool_side = _Recorder(), _Recorder()
    PytestGate().run(gate_side)
    SandboxedToolExecutor(PolicyEngine(_contract()), tool_side).execute(
        ToolRequest(tool=ToolName.RUN_TESTS)
    )
    (gate_exe, gate_args), (tool_exe, tool_args) = gate_side.calls[0], tool_side.calls[0]
    assert tool_exe == gate_exe == "pytest"
    assert _without_report_file(tool_args) == _without_report_file(gate_args)


def test_run_lint_profile_is_the_ruff_gate_normal_check() -> None:
    gate_side, tool_side = _Recorder(), _Recorder()
    RuffGate().run(gate_side)
    SandboxedToolExecutor(PolicyEngine(_contract()), tool_side).execute(
        ToolRequest(tool=ToolName.RUN_LINT)
    )
    assert tool_side.calls == gate_side.calls
    assert "--fix" not in tool_side.calls[0][1]
    assert not any(a.startswith("--config") for a in tool_side.calls[0][1])


def test_run_tests_path_is_the_only_thing_the_agent_controls() -> None:
    recorder = _Recorder()
    SandboxedToolExecutor(PolicyEngine(_contract()), recorder).execute(
        ToolRequest(tool=ToolName.RUN_TESTS, path="tests/test_calculator.py::test_subtract")
    )
    executable, args = recorder.calls[0]
    profile = load_policy_config().profile("run_tests")
    assert executable == profile.executable
    assert _without_report_file(args) == ["tests/test_calculator.py::test_subtract", *profile.argv]


@pytest.mark.parametrize(
    "fields",
    [
        {"executable": "pytest -x"},
        {"executable": "pytest", "argv": ["-q", "tests/; rm -rf /"]},
        {"executable": "pytest", "argv": ["$(curl x)"]},
    ],
)
def test_profiles_are_argv_never_shell_strings(fields: dict) -> None:
    with pytest.raises(ValidationError):
        CommandProfile(id="run_tests", timeout_seconds=10, **fields)


def test_profile_ids_are_unique() -> None:
    profile = CommandProfile(id="run_lint", executable="ruff", timeout_seconds=10)
    with pytest.raises(ValidationError):
        PolicyConfig(profiles=[profile, profile])


def test_pytest_summary_is_structured_and_truncated() -> None:
    long = "assert " + "x" * (MAX_MESSAGE_CHARS * 3)
    tests = [
        {
            "nodeid": f"tests/t.py::test_{i}",
            "outcome": "failed",
            "call": {"outcome": "failed", "crash": {"message": long}},
        }
        for i in range(MAX_FAILURES + 5)
    ]
    report = {"summary": {"passed": 2, "failed": MAX_FAILURES + 5, "skipped": 1}, "tests": tests}
    summary = summarize_pytest_report(report, exit_code=1, target="tests/")
    assert (summary["passed"], summary["failed"], summary["skipped"]) == (2, MAX_FAILURES + 5, 1)
    assert len(summary["failures"]) == MAX_FAILURES
    assert summary["failures_omitted"] == 5
    message = summary["failures"][0]["message"]
    assert message.startswith("assert x")
    assert len(message) < MAX_MESSAGE_CHARS + 50


# --- against a real sandbox -------------------------------------------------------


def _repo(root: Path) -> Path:
    files = {
        "src/calculator.py": "import os\n\n\ndef subtract(a, b):\n    return a + b\n",
        "tests/test_calculator.py": (
            "from calculator import subtract\n\n\ndef test_subtract():\n"
            "    assert subtract(5, 3) == 2\n"
        ),
        "pytest.ini": "[pytest]\npythonpath = src\n",
    }
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")
    return root


def test_run_tests_and_run_lint_on_a_real_workspace(tmp_path: Path) -> None:
    sandbox = LocalCowSandbox(_repo(tmp_path / "repo"))
    sandbox.create()
    try:
        executor = SandboxedToolExecutor(PolicyEngine(_contract()), sandbox)

        tests = executor.execute(ToolRequest(tool=ToolName.RUN_TESTS))
        assert tests.outcome == ExecutionOutcome.FAILED  # the bug is real
        summary = json.loads(tests.output)
        assert summary["failed"] == 1
        assert summary["failures"][0]["nodeid"] == "tests/test_calculator.py::test_subtract"
        assert "assert 8 == 2" in summary["failures"][0]["message"]

        lint = executor.execute(ToolRequest(tool=ToolName.RUN_LINT))
        violations = json.loads(lint.output)["violations"]
        assert [(v["path"], v["code"]) for v in violations] == [("src/calculator.py", "F401")]

        # note 4: only caches were left behind, and those are not changes
        work = sandbox.workdir
        assert (work / ".pytest_cache").exists() or any(work.rglob("__pycache__"))
        assert not any(work.rglob("*report*.json"))  # the report never lands here
        assert sandbox.changed_paths() == []
    finally:
        sandbox.destroy()
