from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from aigis.domain import (
    Attempt,
    ExecutionOutcome,
    PolicyDecision,
    PolicyDecisionType,
    RiskLevel,
    ToolName,
    ToolRequest,
)


def test_finished_at_before_started_at_is_rejected() -> None:
    started = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="finished_at cannot be before"):
        Attempt(
            iteration=1,
            tool_request=ToolRequest(tool=ToolName.READ_FILE, path="README.md"),
            outcome=ExecutionOutcome.COMPLETED,
            started_at=started,
            finished_at=started - timedelta(seconds=1),
        )


def test_policy_decision_must_reference_this_attempts_request() -> None:
    request = ToolRequest(tool=ToolName.READ_FILE, path="README.md")
    other_request = ToolRequest(tool=ToolName.READ_FILE, path="other.md")
    mismatched_decision = PolicyDecision(
        decision=PolicyDecisionType.ALLOW,
        policy_id="PATH-001",
        reason="within allowed_paths",
        risk=RiskLevel.LOW,
        request=other_request,
    )
    with pytest.raises(ValidationError, match="decision for this attempt"):
        Attempt(
            iteration=1,
            tool_request=request,
            policy_decision=mismatched_decision,
            outcome=ExecutionOutcome.POLICY_BLOCKED,
        )


def test_denied_attempt_is_valid_evidence_not_a_crash() -> None:
    """A DENY is a successful control, not a system failure — it must
    produce a normal, well-formed Attempt record (ARCHITECTURE.md section 15/17).
    """
    request = ToolRequest(
        tool=ToolName.RUN_COMMAND, executable="cat", args=["fake_secret.txt"]
    )
    decision = PolicyDecision(
        decision=PolicyDecisionType.DENY,
        policy_id="PATH-004",
        reason="fake_secret.txt is outside allowed_paths",
        risk=RiskLevel.HIGH,
        request=request,
    )
    attempt = Attempt(
        iteration=1,
        tool_request=request,
        policy_decision=decision,
        outcome=ExecutionOutcome.POLICY_BLOCKED,
    )
    assert attempt.policy_decision.decision == PolicyDecisionType.DENY
    assert attempt.outcome == ExecutionOutcome.POLICY_BLOCKED
