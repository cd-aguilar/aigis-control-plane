"""Domain layer: task, state, attempt, evidence, decision.

Pure data models (Pydantic) with the invariants from docs/ARCHITECTURE.md
encoded as validators. Zero I/O, zero dependency on Agent Runtime, Policy
Engine, Sandbox, or any provider — those depend on this module, never the
reverse.
"""

from aigis.domain.agent_claim import AgentClaim
from aigis.domain.attempt import Attempt
from aigis.domain.decision import Decision
from aigis.domain.enums import (
    ExecutionOutcome,
    FinalDecision,
    GateType,
    PolicyDecisionType,
    RiskLevel,
    ToolName,
    VerificationOutcome,
)
from aigis.domain.evidence import EnvironmentMetadata, Evidence
from aigis.domain.policy_decision import PolicyDecision
from aigis.domain.quality_gate import GateResult
from aigis.domain.task_contract import TaskContract
from aigis.domain.task_state import LimitExceeded, TaskState
from aigis.domain.tool_request import ToolRequest

__all__ = [
    "AgentClaim",
    "Attempt",
    "Decision",
    "ExecutionOutcome",
    "FinalDecision",
    "GateType",
    "PolicyDecisionType",
    "RiskLevel",
    "ToolName",
    "VerificationOutcome",
    "Evidence",
    "EnvironmentMetadata",
    "PolicyDecision",
    "GateResult",
    "TaskContract",
    "LimitExceeded",
    "TaskState",
    "ToolRequest",
]
