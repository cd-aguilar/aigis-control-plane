from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aigis.domain import (
    Attempt,
    ExecutionOutcome,
    FinalDecision,
    GateResult,
    PolicyDecision,
    PolicyDecisionType,
    RiskLevel,
    TaskContract,
    TaskState,
    ToolName,
    ToolRequest,
)
from aigis.domain.enums import GateType
from aigis.evaluation.decision_engine import DecisionEngine


def _passing_gates() -> list[GateResult]:
    return [
        GateResult(gate_name="pytest", gate_type=GateType.TEST, passed=True),
        GateResult(gate_name="ruff", gate_type=GateType.LINT, passed=True),
    ]


def _attempt_with_decision(decision_type: PolicyDecisionType, *, path: str = "src/x.py") -> Attempt:
    request = ToolRequest(tool=ToolName.READ_FILE, path=path)
    decision = PolicyDecision(
        decision=decision_type,
        policy_id="TEST-000",
        reason="test fixture",
        risk=RiskLevel.LOW,
        request=request,
    )
    return Attempt(
        iteration=1,
        tool_request=request,
        policy_decision=decision,
        outcome=ExecutionOutcome.COMPLETED
        if decision_type == PolicyDecisionType.ALLOW
        else ExecutionOutcome.POLICY_BLOCKED,
    )


@pytest.fixture
def engine() -> DecisionEngine:
    return DecisionEngine()


def test_all_green_run_is_pass(
    engine: DecisionEngine, contract: TaskContract, fresh_state: TaskState
) -> None:
    fresh_state.attempts.append(_attempt_with_decision(PolicyDecisionType.ALLOW))

    decision = engine.decide(
        run_id="r1", contract=contract, state=fresh_state, gate_results=_passing_gates()
    )

    assert decision.final == FinalDecision.PASS
    assert decision.all_gates_ok


def test_deny_does_not_block_pass_by_itself(
    engine: DecisionEngine, contract: TaskContract, fresh_state: TaskState
) -> None:
    """Per ARCHITECTURE.md section 15: an agent being correctly blocked and
    the task still completing legitimately afterwards is still a PASS -- a
    DENY is evidence the control worked, not a run failure.
    """
    fresh_state.attempts.append(_attempt_with_decision(PolicyDecisionType.DENY))

    decision = engine.decide(
        run_id="r1", contract=contract, state=fresh_state, gate_results=_passing_gates()
    )

    assert decision.final == FinalDecision.PASS


def test_require_human_forces_needs_human_even_with_green_gates(
    engine: DecisionEngine, contract: TaskContract, fresh_state: TaskState
) -> None:
    fresh_state.attempts.append(_attempt_with_decision(PolicyDecisionType.REQUIRE_HUMAN))

    decision = engine.decide(
        run_id="r1", contract=contract, state=fresh_state, gate_results=_passing_gates()
    )

    assert decision.final == FinalDecision.NEEDS_HUMAN
    assert not decision.all_gates_ok


def test_missing_required_gate_is_needs_human_not_fail(
    engine: DecisionEngine, contract: TaskContract, fresh_state: TaskState
) -> None:
    """contract.required_gates includes 'ruff', but only 'pytest' ran -- the
    Decision Engine has no verdict to trust either way, so it escalates
    instead of guessing FAIL.
    """
    only_pytest = [GateResult(gate_name="pytest", gate_type=GateType.TEST, passed=True)]

    decision = engine.decide(
        run_id="r1", contract=contract, state=fresh_state, gate_results=only_pytest
    )

    assert decision.final == FinalDecision.NEEDS_HUMAN


def test_failed_required_gate_is_fail(
    engine: DecisionEngine, contract: TaskContract, fresh_state: TaskState
) -> None:
    gates = [
        GateResult(gate_name="pytest", gate_type=GateType.TEST, passed=False),
        GateResult(gate_name="ruff", gate_type=GateType.LINT, passed=True),
    ]

    decision = engine.decide(run_id="r1", contract=contract, state=fresh_state, gate_results=gates)

    assert decision.final == FinalDecision.FAIL
    assert decision.tests_pass is False


def test_file_changed_outside_scope_is_fail(
    engine: DecisionEngine, contract: TaskContract, fresh_state: TaskState
) -> None:
    """Belt-and-suspenders: even though the Policy Engine should never ALLOW
    a PATCH_FILE outside allowed_paths, the Decision Engine independently
    checks TaskState.files_changed against the contract's scope.
    """
    fresh_state.files_changed.add("README.md")  # outside contract's allowed_paths

    decision = engine.decide(
        run_id="r1", contract=contract, state=fresh_state, gate_results=_passing_gates()
    )

    assert decision.final == FinalDecision.FAIL
    assert decision.scope_ok is False


def test_exceeded_limits_is_fail(
    engine: DecisionEngine, contract: TaskContract, fresh_state: TaskState
) -> None:
    fresh_state.started_at = datetime.now(timezone.utc) - timedelta(
        seconds=contract.max_runtime_seconds + 10
    )

    decision = engine.decide(
        run_id="r1", contract=contract, state=fresh_state, gate_results=_passing_gates()
    )

    assert decision.final == FinalDecision.FAIL
    assert decision.resource_limits_ok is False


def test_decision_carries_evidence_ref(
    engine: DecisionEngine, contract: TaskContract, fresh_state: TaskState
) -> None:
    decision = engine.decide(
        run_id="run-xyz", contract=contract, state=fresh_state, gate_results=_passing_gates()
    )

    assert decision.evidence_ref == "evidence/run-xyz/"
