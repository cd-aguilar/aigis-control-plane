"""Provider — the seam between Agent Runtime and whatever LLM proposes the
next action.

Per ARCHITECTURE.md section 8: "Primer proveedor: Claude API, rol Coder...
La arquitectura debe permitir posteriormente otros providers ... sin
modificar el control plane." Everything in the agent/domain layers depends
only on this protocol and on ProviderAction — never on the Anthropic SDK
directly — so a second provider plugs in later without touching the
runtime, the reducer, or the tool schemas.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from aigis.domain import TaskContract, TaskState, ToolRequest


class ProposeToolRequest(BaseModel):
    """The provider wants to take an action."""

    model_config = {"frozen": True}

    tool_request: ToolRequest


class ClaimDone(BaseModel):
    """The provider believes the task is finished and is not proposing
    another tool call. This is a CLAIM, not a decision — see AgentClaim's
    docstring and the project's central thesis.
    """

    model_config = {"frozen": True}

    message: str = Field(min_length=1)


ProviderAction = ProposeToolRequest | ClaimDone


class Provider(Protocol):
    """Stateless by contract: everything the provider needs to decide the
    next action — the task, prior tool calls, prior claims — is derivable
    from `contract` and `state` alone (TaskState.attempts / .agent_claims
    hold full history). The provider must never keep its own conversation
    state between calls, per ARCHITECTURE.md section 8's stateless-reducer
    model: execution state lives explicitly outside the LLM.
    """

    def propose_action(self, contract: TaskContract, state: TaskState) -> ProviderAction: ...
