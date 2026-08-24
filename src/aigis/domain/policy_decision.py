"""PolicyDecision — the Policy Engine's verdict on a ToolRequest.

Per ARCHITECTURE.md section 10: "Esto convierte la autorización en parte de
la evidencia." A PolicyDecision is not a log line, it's evidence — every
field here is expected to be serialized straight into
``evidence/<run-id>/events.jsonl``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from aigis.domain.enums import PolicyDecisionType, RiskLevel
from aigis.domain.tool_request import ToolRequest


class PolicyDecision(BaseModel):
    """The Policy Engine is deterministic and external to the LLM: the LLM
    never sees or influences this model, it only receives the outcome.
    """

    model_config = {"frozen": True}

    decision: PolicyDecisionType
    policy_id: str = Field(min_length=1, description="e.g. 'CMD-001', 'PATH-003'")
    reason: str = Field(min_length=1)
    risk: RiskLevel
    request: ToolRequest
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
