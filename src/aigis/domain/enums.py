"""Enumerations shared across the AIGIS Control Plane domain layer.

These encode the vocabulary defined in docs/ARCHITECTURE.md (sections 7, 10,
15, 21 in particular) as concrete, importable types instead of free-form
strings scattered across the codebase.
"""

from __future__ import annotations

from enum import Enum


class RiskLevel(str, Enum):
    """Risk classification of a task, per ARCHITECTURE.md section 7.

    Not yet wired into automatic policy behavior in Phase 0 — the mapping
    (LOW -> automatic, MEDIUM -> automatic + evidence, HIGH -> REQUIRE_HUMAN,
    CRITICAL -> DENY) belongs to the Policy Engine (Phase 3). It is captured
    here from the start so TaskContract never needs a breaking schema change
    to support it later.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolName(str, Enum):
    """The only capabilities the agent may request. Least privilege by
    construction: there is no ``run_any_command`` or ``write_file`` member.
    """

    READ_FILE = "read_file"
    PATCH_FILE = "patch_file"
    RUN_COMMAND = "run_command"


class PolicyDecisionType(str, Enum):
    """Outcome of the Policy Engine evaluating a ToolRequest (section 3.1, 10)."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"


class ExecutionOutcome(str, Enum):
    """State of a run's execution, independent of whether it was verified
    correct (section 15: "Execution Outcome" is distinct from
    "Verification Outcome" and "Final Decision").
    """

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    RESOURCE_EXCEEDED = "RESOURCE_EXCEEDED"


class VerificationOutcome(str, Enum):
    """Result of evaluating evidence against the contract (section 15)."""

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class FinalDecision(str, Enum):
    """The only three things the Decision Engine is allowed to say (section 15,
    3.6). Never derived from the agent's own claim of completion.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class GateType(str, Enum):
    """Category of a deterministic quality gate (section 12)."""

    TEST = "TEST"
    LINT = "LINT"
    SECURITY = "SECURITY"
    CUSTOM = "CUSTOM"
