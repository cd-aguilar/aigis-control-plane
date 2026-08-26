from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aigis.domain import ExecutionOutcome, PolicyDecisionType, TaskContract, ToolName, ToolRequest
from aigis.policy.config import PolicyConfig
from aigis.policy.engine import PolicyEngine
from aigis.policy.executor import SandboxedToolExecutor
from aigis.sandbox.base import CommandResult
from aigis.sandbox.local_cow import LocalCowSandbox


class FakeSandbox:
    """Test double satisfying the Sandbox protocol -- records every call so
    tests can assert the executor never reaches the sandbox for a DENYed
    request (the whole point of checking policy first).
    """

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = dict(files or {})
        self.calls: list[tuple[str, ...]] = []
        self.command_result = CommandResult(exit_code=0, stdout="ok", stderr="")

    def create(self) -> None:
        self.calls.append(("create",))

    def read_file(self, path: str) -> str:
        self.calls.append(("read_file", path))
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_file(self, path: str, content: str) -> None:
        self.calls.append(("write_file", path))
        self.files[path] = content

    def run_command(
        self, executable: str, args: list[str], *, timeout_seconds: int
    ) -> CommandResult:
        self.calls.append(("run_command", executable, *args))
        return self.command_result

    def collect_diff(self) -> str:
        return ""

    def destroy(self) -> None:
        self.calls.append(("destroy",))


@pytest.fixture
def policy_engine(contract: TaskContract) -> PolicyEngine:
    return PolicyEngine(contract, PolicyConfig(allowed_commands=["pytest"]))


@pytest.fixture
def sandbox() -> FakeSandbox:
    return FakeSandbox(files={"src/math_utils.py": "def add(a, b):\n    return a - b\n"})


@pytest.fixture
def executor(policy_engine: PolicyEngine, sandbox: FakeSandbox) -> SandboxedToolExecutor:
    return SandboxedToolExecutor(policy_engine, sandbox)


# --- DENY short-circuits before the sandbox is touched -------------------------


def test_denied_request_never_reaches_the_sandbox(
    executor: SandboxedToolExecutor, sandbox: FakeSandbox
) -> None:
    request = ToolRequest(tool=ToolName.READ_FILE, path="README.md")  # outside allowed_paths
    result = executor.execute(request)

    assert result.outcome == ExecutionOutcome.POLICY_BLOCKED
    assert result.policy_decision is not None
    assert result.policy_decision.decision == PolicyDecisionType.DENY
    assert sandbox.calls == []


def test_denied_result_error_message_includes_policy_id_and_reason(
    executor: SandboxedToolExecutor,
) -> None:
    request = ToolRequest(tool=ToolName.RUN_COMMAND, executable="rm", args=["-rf", "/"])
    result = executor.execute(request)

    assert "CMD-001" in result.error
    assert "DENY" in result.error


# --- ALLOW: READ_FILE ------------------------------------------------------------


def test_allowed_read_returns_file_contents(executor: SandboxedToolExecutor) -> None:
    request = ToolRequest(tool=ToolName.READ_FILE, path="src/math_utils.py")
    result = executor.execute(request)

    assert result.outcome == ExecutionOutcome.COMPLETED
    assert "return a - b" in result.output
    assert result.policy_decision.decision == PolicyDecisionType.ALLOW


def test_read_of_missing_file_is_failed_not_an_exception(executor: SandboxedToolExecutor) -> None:
    request = ToolRequest(tool=ToolName.READ_FILE, path="src/does_not_exist.py")
    result = executor.execute(request)

    assert result.outcome == ExecutionOutcome.FAILED
    assert result.error


# --- ALLOW: PATCH_FILE -----------------------------------------------------------


def test_allowed_patch_applies_str_replace_and_reports_changed_path(
    executor: SandboxedToolExecutor, sandbox: FakeSandbox
) -> None:
    request = ToolRequest(
        tool=ToolName.PATCH_FILE,
        path="src/math_utils.py",
        old_str="return a - b",
        new_str="return a + b",
    )
    result = executor.execute(request)

    assert result.outcome == ExecutionOutcome.COMPLETED
    assert result.changed_path == "src/math_utils.py"
    assert "return a + b" in sandbox.files["src/math_utils.py"]


def test_patch_with_old_str_not_found_is_failed(executor: SandboxedToolExecutor) -> None:
    request = ToolRequest(
        tool=ToolName.PATCH_FILE,
        path="src/math_utils.py",
        old_str="this text is not in the file",
        new_str="anything",
    )
    result = executor.execute(request)

    assert result.outcome == ExecutionOutcome.FAILED
    assert "not found" in result.error


def test_patch_with_non_unique_old_str_is_failed(
    executor: SandboxedToolExecutor, sandbox: FakeSandbox
) -> None:
    sandbox.files["src/dup.py"] = "x = 1\nx = 1\n"
    request = ToolRequest(
        tool=ToolName.PATCH_FILE, path="src/dup.py", old_str="x = 1", new_str="x = 2"
    )
    result = executor.execute(request)

    assert result.outcome == ExecutionOutcome.FAILED
    assert "not unique" in result.error


# --- ALLOW: RUN_COMMAND -----------------------------------------------------------


def test_allowed_command_completed_maps_zero_exit_code(
    executor: SandboxedToolExecutor, sandbox: FakeSandbox
) -> None:
    sandbox.command_result = CommandResult(exit_code=0, stdout="2 passed", stderr="")
    request = ToolRequest(tool=ToolName.RUN_COMMAND, executable="pytest", args=["tests/"])
    result = executor.execute(request)

    assert result.outcome == ExecutionOutcome.COMPLETED
    assert result.output == "2 passed"
    assert result.error is None


def test_allowed_command_nonzero_exit_code_is_failed(
    executor: SandboxedToolExecutor, sandbox: FakeSandbox
) -> None:
    sandbox.command_result = CommandResult(exit_code=1, stdout="", stderr="1 failed")
    request = ToolRequest(tool=ToolName.RUN_COMMAND, executable="pytest", args=["tests/"])
    result = executor.execute(request)

    assert result.outcome == ExecutionOutcome.FAILED
    assert result.error == "1 failed"


def test_allowed_command_timeout_maps_to_timeout_outcome(
    executor: SandboxedToolExecutor, sandbox: FakeSandbox
) -> None:
    sandbox.command_result = CommandResult(exit_code=-1, stdout="", stderr="", timed_out=True)
    request = ToolRequest(tool=ToolName.RUN_COMMAND, executable="pytest", args=[])
    result = executor.execute(request)

    assert result.outcome == ExecutionOutcome.TIMEOUT


# --- end-to-end with a real LocalCowSandbox (no mocks) ---------------------------


def test_end_to_end_with_real_sandbox(tmp_path: Path) -> None:
    repo = tmp_path / "toy-repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "math_utils.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )

    contract = TaskContract(
        task_id="T-e2e",
        description="fix add()",
        allowed_paths=["src/"],
        success_criteria=["add(2, 2) == 4"],
        required_gates=["pytest"],
        max_iterations=5,
        max_runtime_seconds=60,
        max_tool_calls=10,
        max_files_changed=2,
    )
    policy_engine = PolicyEngine(
        contract, PolicyConfig(allowed_commands=["python", sys.executable])
    )
    real_sandbox = LocalCowSandbox(repo)
    real_sandbox.create()
    # written straight to the sandbox filesystem (not through a ToolRequest)
    # purely as test setup -- run_command's args can't carry ';' or '\n'
    # (ToolRequest's own shell-metacharacter guard), so a one-line -c script
    # can't express "import, call, assert" as separate statements. A real
    # agent would PATCH_FILE this in, same as math_utils.py above.
    real_sandbox.write_file(
        "src/check_add.py",
        "import math_utils\nassert math_utils.add(2, 2) == 4\n",
    )
    executor = SandboxedToolExecutor(policy_engine, real_sandbox)

    try:
        patch = executor.execute(
            ToolRequest(
                tool=ToolName.PATCH_FILE,
                path="src/math_utils.py",
                old_str="return a - b",
                new_str="return a + b",
            )
        )
        assert patch.outcome == ExecutionOutcome.COMPLETED

        run = executor.execute(
            ToolRequest(
                tool=ToolName.RUN_COMMAND,
                executable=sys.executable,
                args=["src/check_add.py"],
            )
        )
        assert run.outcome == ExecutionOutcome.COMPLETED, run.error

        diff = real_sandbox.collect_diff()
        assert "+    return a + b" in diff
    finally:
        real_sandbox.destroy()
