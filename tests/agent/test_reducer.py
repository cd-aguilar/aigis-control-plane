from datetime import datetime, timedelta, timezone

from aigis.agent import reducer
from aigis.agent.executor import ExecutionResult
from aigis.agent.provider import ClaimDone
from aigis.domain import ExecutionOutcome, TaskContract, TaskState, ToolName, ToolRequest


def test_circuit_breaker_reports_no_breach_on_fresh_state(
    contract: TaskContract, fresh_state: TaskState
) -> None:
    stopped = reducer.apply_circuit_breaker(contract, fresh_state)
    assert stopped is False
    assert fresh_state.status == ExecutionOutcome.RUNNING


def test_circuit_breaker_sets_resource_exceeded_on_iteration_breach(
    contract: TaskContract, fresh_state: TaskState
) -> None:
    fresh_state.iteration = contract.max_iterations + 1

    stopped = reducer.apply_circuit_breaker(contract, fresh_state)

    assert stopped is True
    assert fresh_state.status == ExecutionOutcome.RESOURCE_EXCEEDED


def test_circuit_breaker_sets_timeout_on_runtime_breach(
    contract: TaskContract, fresh_state: TaskState
) -> None:
    fresh_state.started_at = datetime.now(timezone.utc) - timedelta(
        seconds=contract.max_runtime_seconds + 1
    )

    stopped = reducer.apply_circuit_breaker(contract, fresh_state)

    assert stopped is True
    assert fresh_state.status == ExecutionOutcome.TIMEOUT


def test_apply_claim_done_records_claim_and_leaves_status_running(fresh_state: TaskState) -> None:
    claim = reducer.apply_claim_done(fresh_state, ClaimDone(message="I'm done."))

    assert fresh_state.agent_claims == [claim]
    assert claim.message == "I'm done."
    assert claim.iteration == 1  # fresh_state.iteration (0) + 1
    assert fresh_state.status == ExecutionOutcome.RUNNING


def test_apply_execution_result_records_attempt(fresh_state: TaskState) -> None:
    tool_request = ToolRequest(tool=ToolName.READ_FILE, path="README.md")
    result = ExecutionResult(outcome=ExecutionOutcome.COMPLETED, output="hello")
    started_at = datetime.now(timezone.utc)

    attempt = reducer.apply_execution_result(
        fresh_state, tool_request, result, started_at=started_at
    )

    assert fresh_state.attempts == [attempt]
    assert fresh_state.tool_calls_count == 1
    assert attempt.tool_request == tool_request
    assert attempt.output == "hello"
    assert attempt.outcome == ExecutionOutcome.COMPLETED


def test_apply_execution_result_tracks_changed_path(fresh_state: TaskState) -> None:
    tool_request = ToolRequest(
        tool=ToolName.PATCH_FILE, path="src/x.py", old_str="a", new_str="b"
    )
    result = ExecutionResult(
        outcome=ExecutionOutcome.COMPLETED, output="patched", changed_path="src/x.py"
    )

    reducer.apply_execution_result(
        fresh_state, tool_request, result, started_at=datetime.now(timezone.utc)
    )

    assert fresh_state.files_changed == {"src/x.py"}


def test_apply_execution_result_carries_policy_denial(fresh_state: TaskState) -> None:
    from aigis.domain import PolicyDecision, PolicyDecisionType, RiskLevel

    tool_request = ToolRequest(
        tool=ToolName.RUN_COMMAND, executable="cat", args=["fake_secret.txt"]
    )
    decision = PolicyDecision(
        decision=PolicyDecisionType.DENY,
        policy_id="PATH-004",
        reason="fake_secret.txt is outside allowed_paths",
        risk=RiskLevel.HIGH,
        request=tool_request,
    )
    result = ExecutionResult(outcome=ExecutionOutcome.POLICY_BLOCKED, policy_decision=decision)

    attempt = reducer.apply_execution_result(
        fresh_state, tool_request, result, started_at=datetime.now(timezone.utc)
    )

    assert attempt.outcome == ExecutionOutcome.POLICY_BLOCKED
    assert attempt.policy_decision.decision == PolicyDecisionType.DENY
