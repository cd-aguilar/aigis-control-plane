"""Attempt — a single iteration of the agent loop: one tool request, its
policy verdict, and what actually happened.

The Agent Runtime (Phase 2) is a stateless reducer: ``(state, event) ->
new_state``. An Attempt is the "event" half of that pair — TaskState
(Phase 1) is the "state" half. Neither model depends on the other's
implementation, only on this shared vocabulary.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from aigis.domain.enums import ExecutionOutcome
from aigis.domain.policy_decision import PolicyDecision
from aigis.domain.tool_request import ToolRequest


class Attempt(BaseModel):
    model_config = {"frozen": True}

    iteration: int = Field(ge=1)
    tool_request: ToolRequest

    # None until the Policy Engine (Phase 3) runs. A DENY here still produces
    # a COMPLETE Attempt record — a blocked action is evidence, not a crash.
    policy_decision: PolicyDecision | None = None

    outcome: ExecutionOutcome
    output: str | None = None
    error: str | None = None

    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def _finished_after_started(self) -> Attempt:
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be before started_at")
        if self.policy_decision is not None:
            if self.policy_decision.request.request_id != self.tool_request.request_id:
                raise ValueError(
                    "policy_decision.request must be the decision for this "
                    "attempt's own tool_request"
                )
        return self
