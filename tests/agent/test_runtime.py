from aigis.agent.executor import ExecutionResult
from aigis.agent.provider import ClaimDone, ProposeToolRequest
from aigis.agent.runtime import AgentRuntime
from aigis.domain import ExecutionOutcome, TaskContract, TaskState, ToolName, ToolRequest
from tests.agent.conftest import FakeExecutor, FakeProvider


def _read_action(path: str = "README.md") -> ProposeToolRequest:
    return ProposeToolRequest(tool_request=ToolRequest(tool=ToolName.READ_FILE, path=path))


def test_step_with_tool_request_records_one_attempt(
    contract: TaskContract, fresh_state: TaskState
) -> None:
    provider = FakeProvider([_read_action()])
    executor = FakeExecutor([ExecutionResult(outcome=ExecutionOutcome.COMPLETED, output="hi")])
    runtime = AgentRuntime(contract, provider, executor)

    runtime.step(fresh_state)

    assert len(fresh_state.attempts) == 1
    assert fresh_state.status == ExecutionOutcome.RUNNING
    assert len(executor.calls) == 1


def test_step_with_claim_done_records_claim_not_attempt(
    contract: TaskContract, fresh_state: TaskState
) -> None:
    provider = FakeProvider([ClaimDone(message="Task is done.")])
    executor = FakeExecutor()
    runtime = AgentRuntime(contract, provider, executor)

    runtime.step(fresh_state)

    assert len(fresh_state.agent_claims) == 1
    assert fresh_state.attempts == []
    assert fresh_state.status == ExecutionOutcome.RUNNING
    assert executor.calls == []  # a claim never touches the executor


def test_step_is_noop_once_terminal(contract: TaskContract, fresh_state: TaskState) -> None:
    fresh_state.status = ExecutionOutcome.FAILED
    provider = FakeProvider([_read_action()])
    executor = FakeExecutor()
    runtime = AgentRuntime(contract, provider, executor)

    runtime.step(fresh_state)

    assert provider.calls == []
    assert executor.calls == []
    assert fresh_state.status == ExecutionOutcome.FAILED


def test_step_stops_at_circuit_breaker_before_calling_provider(
    contract: TaskContract, fresh_state: TaskState
) -> None:
    fresh_state.iteration = contract.max_iterations + 1
    provider = FakeProvider([_read_action()])
    executor = FakeExecutor()
    runtime = AgentRuntime(contract, provider, executor)

    runtime.step(fresh_state)

    assert provider.calls == []
    assert fresh_state.status == ExecutionOutcome.RESOURCE_EXCEEDED


def test_run_loops_through_tool_calls_then_stops_on_claim(
    contract: TaskContract, fresh_state: TaskState
) -> None:
    provider = FakeProvider(
        [_read_action("a.py"), _read_action("b.py"), ClaimDone(message="Done.")]
    )
    executor = FakeExecutor(
        [
            ExecutionResult(outcome=ExecutionOutcome.COMPLETED, output="a"),
            ExecutionResult(outcome=ExecutionOutcome.COMPLETED, output="b"),
        ]
    )
    runtime = AgentRuntime(contract, provider, executor)

    runtime.run(fresh_state)

    assert len(fresh_state.attempts) == 2
    assert len(fresh_state.agent_claims) == 1
    # A claim stops the loop from asking for more actions, but it is NOT a
    # verdict -- status must still be RUNNING, awaiting the Decision Engine.
    assert fresh_state.status == ExecutionOutcome.RUNNING


def test_run_stops_at_circuit_breaker_one_iteration_past_the_limit(
    contract: TaskContract, fresh_state: TaskState
) -> None:
    """Matches TaskState.exceeded_limits' own semantics (breach is detected
    only once actual > contract_value): with max_iterations=N, exactly N+1
    attempts get executed before the breach is caught on the next step.
    """
    always_read = [_read_action(f"file_{i}.py") for i in range(contract.max_iterations + 3)]
    provider = FakeProvider(always_read)
    executor = FakeExecutor(
        [ExecutionResult(outcome=ExecutionOutcome.COMPLETED, output="ok") for _ in always_read]
    )
    runtime = AgentRuntime(contract, provider, executor)

    runtime.run(fresh_state)

    assert len(fresh_state.attempts) == contract.max_iterations + 1
    assert fresh_state.status == ExecutionOutcome.RESOURCE_EXCEEDED


def test_run_never_calls_provider_when_state_starts_terminal(
    contract: TaskContract, fresh_state: TaskState
) -> None:
    fresh_state.status = ExecutionOutcome.CANCELLED
    provider = FakeProvider([_read_action()])
    executor = FakeExecutor()
    runtime = AgentRuntime(contract, provider, executor)

    runtime.run(fresh_state)

    assert provider.calls == []
