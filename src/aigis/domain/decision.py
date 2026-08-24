"""Decision — the only output that matters. Never derived from what the
agent says about itself.

Per the project's central thesis: "The agent can claim it is done. The
system decides whether it is true." The formula from CLAUDE.md /
ARCHITECTURE.md section 3.2 is enforced structurally, not just documented:

    contract_valid AND policy_ok AND tests_pass
    AND lint_pass AND scope_ok AND resource_limits_ok
    => final == PASS

If any of the six booleans is False, ``final`` must NOT be PASS — the model
itself rejects a Decision that claims PASS while a gate says otherwise. The
Decision Engine (Phase 4) still chooses between FAIL and NEEDS_HUMAN (per
the fail-closed principle, section 3.6); this model only forbids it from
ever mislabeling a failed check as a pass.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from aigis.domain.enums import FinalDecision


class Decision(BaseModel):
    model_config = {"frozen": True}

    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)

    contract_valid: bool
    policy_ok: bool
    tests_pass: bool
    lint_pass: bool
    scope_ok: bool
    resource_limits_ok: bool

    final: FinalDecision
    reason: str = Field(min_length=1)
    evidence_ref: str | None = Field(
        default=None, description="Path or run-id pointing at the Evidence Bundle."
    )

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def all_gates_ok(self) -> bool:
        return (
            self.contract_valid
            and self.policy_ok
            and self.tests_pass
            and self.lint_pass
            and self.scope_ok
            and self.resource_limits_ok
        )

    @model_validator(mode="after")
    def _final_matches_gates(self) -> Decision:
        if self.all_gates_ok and self.final != FinalDecision.PASS:
            raise ValueError(
                "all six gates are satisfied but final != PASS — the agent's "
                "own claim is irrelevant, but the Decision Engine still must "
                "follow the formula it defines"
            )
        if not self.all_gates_ok and self.final == FinalDecision.PASS:
            raise ValueError(
                "final == PASS but at least one gate is False — PASS may "
                "only be issued when contract_valid AND policy_ok AND "
                "tests_pass AND lint_pass AND scope_ok AND "
                "resource_limits_ok are all True"
            )
        return self
