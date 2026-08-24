import pytest
from pydantic import ValidationError

from aigis.domain import Decision, FinalDecision


def _decision(**overrides) -> Decision:
    fields = dict(
        run_id="r1",
        task_id="T01",
        contract_valid=True,
        policy_ok=True,
        tests_pass=True,
        lint_pass=True,
        scope_ok=True,
        resource_limits_ok=True,
        final=FinalDecision.PASS,
        reason="all gates green",
    )
    fields.update(overrides)
    return Decision(**fields)


def test_all_gates_true_allows_pass() -> None:
    decision = _decision()
    assert decision.all_gates_ok
    assert decision.final == FinalDecision.PASS


def test_all_gates_true_but_final_fail_is_rejected() -> None:
    """Even if someone tries to report FAIL when every gate actually passed,
    the model should not silently accept a decision that contradicts its own
    formula.
    """
    with pytest.raises(ValidationError, match="all six gates are satisfied"):
        _decision(final=FinalDecision.FAIL)


@pytest.mark.parametrize(
    "failing_field",
    [
        "contract_valid",
        "policy_ok",
        "tests_pass",
        "lint_pass",
        "scope_ok",
        "resource_limits_ok",
    ],
)
def test_any_gate_false_forbids_pass(failing_field: str) -> None:
    """This is the structural version of the thesis: 'the agent can claim it
    is done, the system decides whether it's true' — a Decision literally
    cannot be constructed claiming PASS while one gate is False.
    """
    with pytest.raises(ValidationError, match="PASS may only be issued"):
        _decision(**{failing_field: False}, final=FinalDecision.PASS)


def test_any_gate_false_allows_fail() -> None:
    decision = _decision(tests_pass=False, final=FinalDecision.FAIL, reason="tests failed")
    assert not decision.all_gates_ok
    assert decision.final == FinalDecision.FAIL


def test_any_gate_false_allows_needs_human() -> None:
    decision = _decision(
        policy_ok=False, final=FinalDecision.NEEDS_HUMAN, reason="policy inconclusive"
    )
    assert not decision.all_gates_ok
    assert decision.final == FinalDecision.NEEDS_HUMAN


def test_decision_is_frozen() -> None:
    decision = _decision()
    with pytest.raises(ValidationError):
        decision.final = FinalDecision.FAIL
