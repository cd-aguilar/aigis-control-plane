"""AgentClaim — a record of the agent SAYING it is done. Never authoritative.

Central thesis: "The agent can claim it is done. The system decides whether
it is true." An AgentClaim is deliberately NOT an Attempt: an Attempt wraps a
ToolRequest that went through Policy Engine + Sandbox and produced real,
verifiable evidence. A claim is just text the LLM emitted instead of
proposing another tool call. It gets logged for the record — the Agent
Runtime stops asking the agent for more actions once it claims done — but
the Decision Engine (Phase 4) never reads AgentClaim.message to decide
PASS/FAIL/NEEDS_HUMAN. Only Evidence + Quality Gates do that.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class AgentClaim(BaseModel):
    model_config = {"frozen": True}

    iteration: int = Field(ge=1)
    message: str = Field(min_length=1)
    claimed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
