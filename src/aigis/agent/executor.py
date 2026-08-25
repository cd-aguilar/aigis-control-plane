"""ToolExecutor — the seam between Agent Runtime and everything that
actually DOES something (Policy Engine + Sandbox, Phase 3).

The runtime never touches the filesystem, a subprocess, or the network
itself; it only calls ``execute()`` on whatever ToolExecutor it was given.
This keeps Phase 2 (Agent Runtime) fully testable without Docker, and means
Phase 3 only has to provide one class that satisfies this protocol — no
changes to the runtime, the reducer, or the provider.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from aigis.domain import ExecutionOutcome, PolicyDecision, ToolRequest


class ExecutionResult(BaseModel):
    """What came back from actually attempting a ToolRequest — regardless of
    whether it was ALLOWed and ran, or DENYed by the Policy Engine before it
    ever reached the sandbox. A DENY is still a normal ExecutionResult, not
    an exception: per ARCHITECTURE.md section 15/17, a blocked action is
    evidence the control worked, not a system failure.
    """

    model_config = {"frozen": True}

    outcome: ExecutionOutcome
    output: str | None = None
    error: str | None = None
    policy_decision: PolicyDecision | None = None
    changed_path: str | None = None


class ToolExecutor(Protocol):
    """Implemented for real in Phase 3 by something backed by the Policy
    Engine + Sandbox. Implemented by a test double here in Phase 2.
    """

    def execute(self, tool_request: ToolRequest) -> ExecutionResult: ...
