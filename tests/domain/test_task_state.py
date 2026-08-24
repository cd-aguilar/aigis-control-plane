from datetime import datetime, timedelta, timezone

from aigis.domain import Attempt, ExecutionOutcome, TaskContract, TaskState, ToolName, ToolRequest


def _attempt(iteration: int) -> Attempt:
    return Attempt(
        iteration=iteration,
        tool_request=ToolRequest(tool=ToolName.READ_FILE, path="README.md"),
        outcome=ExecutionOutcome.COMPLETED,
    )


def test_fresh_state_is_within_limits(contract: TaskContract) -> None:
    state = TaskState(run_id="r1", task_id=contract.task_id)
    assert state.is_within_limits(contract)
    assert state.exceeded_limits(contract) == []


def test_record_attempt_updates_counters(contract: TaskContract) -> None:
    state = TaskState(run_id="r1", task_id=contract.task_id)
    state.record_attempt(_attempt(1), changed_path="src/aigis/domain/x.py")
    state.record_attempt(_attempt(2), changed_path="src/aigis/domain/y.py")

    assert state.iteration == 2
    assert state.tool_calls_count == 2
    assert state.files_changed == {"src/aigis/domain/x.py", "src/aigis/domain/y.py"}
    assert len(state.attempts) == 2


def test_exceeding_max_iterations_is_detected(contract: TaskContract) -> None:
    state = TaskState(run_id="r1", task_id=contract.task_id)
    for i in range(1, contract.max_iterations + 2):  # one past the limit
        state.record_attempt(_attempt(i))

    breaches = state.exceeded_limits(contract)
    assert any(b.limit == "max_iterations" for b in breaches)
    assert not state.is_within_limits(contract)


def test_exceeding_max_files_changed_is_detected(contract: TaskContract) -> None:
    state = TaskState(run_id="r1", task_id=contract.task_id)
    for i, path in enumerate(["a.py", "b.py", "c.py", "d.py"], start=1):
        state.record_attempt(_attempt(i), changed_path=path)

    breaches = state.exceeded_limits(contract)
    assert any(b.limit == "max_files_changed" for b in breaches)


def test_exceeding_max_runtime_is_detected(contract: TaskContract) -> None:
    started = datetime.now(timezone.utc) - timedelta(seconds=contract.max_runtime_seconds + 1)
    state = TaskState(run_id="r1", task_id=contract.task_id, started_at=started)

    breaches = state.exceeded_limits(contract)
    assert any(b.limit == "max_runtime_seconds" for b in breaches)


def test_limit_exceeded_reports_contract_and_actual_values(contract: TaskContract) -> None:
    state = TaskState(run_id="r1", task_id=contract.task_id)
    for i in range(1, contract.max_iterations + 2):
        state.record_attempt(_attempt(i))

    breach = next(b for b in state.exceeded_limits(contract) if b.limit == "max_iterations")
    assert breach.contract_value == contract.max_iterations
    assert breach.actual_value == contract.max_iterations + 1
