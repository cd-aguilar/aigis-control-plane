"""ClaudeProvider — the first (and, in this phase, only) Provider
implementation, per ARCHITECTURE.md section 8: "Primer proveedor: Claude
API, rol Coder." Everything else in the agent layer only depends on the
Provider protocol (agent/provider.py), so a second provider (OpenAI,
Gemini, a local model) plugs in later without touching the runtime, the
reducer, or the tool schemas.

The translation functions (build_system_prompt / build_messages /
parse_response) are pure and duck-typed on purpose, so they're fully unit
tested with plain stub objects — no network call, and no dependency on the
``anthropic`` package at import time. Only constructing ``ClaudeProvider``
itself needs the package installed and ``ANTHROPIC_API_KEY`` set.
"""

from __future__ import annotations

import os
from typing import Any

from aigis.agent.provider import ClaimDone, ProposeToolRequest, ProviderAction
from aigis.agent.tools import TOOL_SCHEMAS, tool_request_from_call
from aigis.domain import (
    Attempt,
    ExecutionOutcome,
    PolicyDecisionType,
    TaskContract,
    TaskState,
    ToolName,
)

# NOTE: confirm this against Anthropic's currently available model IDs
# before actually running the agent — this is scaffolding, not a verified
# production value. Override via the `model` constructor arg or the
# AIGIS_CLAUDE_MODEL env var.
_DEFAULT_MODEL = "claude-sonnet-4-5"

CODER_SYSTEM_PROMPT_TEMPLATE = """\
You are the Coder agent inside the AIGIS Control Plane.

You do not have authority to decide whether your work is complete or \
correct -- the system verifies that from evidence (tests, lint, policy \
decisions), never from what you say. Use the available tools to make \
progress on the task below. When you believe you have finished, respond \
with a plain text message explaining what you did and why you believe the \
task is complete, and do not call a tool in that same message. The system \
will independently verify your work from the evidence you produced.

Task ID: {task_id}
Description: {description}
Allowed paths: {allowed_paths}
Forbidden paths: {forbidden_paths}
Success criteria: {success_criteria}
Risk level: {risk_level}
"""


def build_system_prompt(contract: TaskContract) -> str:
    return CODER_SYSTEM_PROMPT_TEMPLATE.format(
        task_id=contract.task_id,
        description=contract.description,
        allowed_paths=", ".join(contract.allowed_paths),
        forbidden_paths=", ".join(contract.forbidden_paths) or "(none)",
        success_criteria="; ".join(contract.success_criteria),
        risk_level=contract.risk_level.value,
    )


def _tool_input_for_attempt(attempt: Attempt) -> dict[str, Any]:
    req = attempt.tool_request
    if req.tool is ToolName.READ_FILE:
        return {"path": req.path}
    if req.tool is ToolName.PATCH_FILE:
        return {"path": req.path, "old_str": req.old_str, "new_str": req.new_str}
    return {"executable": req.executable, "args": req.args}


def _tool_result_text(attempt: Attempt) -> str:
    decision = attempt.policy_decision
    if decision is not None and decision.decision == PolicyDecisionType.DENY:
        return f"DENIED by policy ({decision.policy_id}): {decision.reason}"
    if attempt.error:
        return f"error: {attempt.error}"
    return attempt.output or "(no output)"


def build_messages(state: TaskState) -> list[dict[str, Any]]:
    """Reconstruct the Claude conversation from ``state.attempts`` +
    ``state.agent_claims``, interleaved in iteration order, so the provider
    stays stateless across calls — ARCHITECTURE.md section 8 requires
    execution state to live explicitly outside the model, never inside a
    stateful chat session on the provider's side.
    """
    events: list[tuple[int, str, Any]] = [
        (attempt.iteration, "attempt", attempt) for attempt in state.attempts
    ]
    events += [(claim.iteration, "claim", claim) for claim in state.agent_claims]
    events.sort(key=lambda item: item[0])

    messages: list[dict[str, Any]] = []
    for _, kind, event in events:
        if kind == "attempt":
            tool_use_id = event.tool_request.request_id
            messages.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": event.tool_request.tool.value,
                            "input": _tool_input_for_attempt(event),
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": _tool_result_text(event),
                            "is_error": event.outcome == ExecutionOutcome.FAILED,
                        }
                    ],
                }
            )
        else:
            messages.append({"role": "assistant", "content": event.message})
    return messages


def parse_response(content_blocks: list[Any]) -> ProviderAction:
    """Turn the Anthropic response's content blocks into a ProviderAction.

    Duck-typed on purpose (checks ``.type``, ``.name``, ``.input``,
    ``.text``) so this stays testable with plain stub objects, without
    importing the anthropic SDK's types into the test suite.
    """
    for block in content_blocks:
        if getattr(block, "type", None) == "tool_use":
            tool_request = tool_request_from_call(block.name, dict(block.input))
            return ProposeToolRequest(tool_request=tool_request)

    text = "\n".join(
        block.text for block in content_blocks if getattr(block, "type", None) == "text"
    ).strip()
    return ClaimDone(message=text or "(agent returned no tool call and no text)")


class ClaudeProvider:
    """Provider implementation backed by the real Claude API.

    Reads the API key from ``ANTHROPIC_API_KEY`` (CLAUDE.md: "una sola
    credencial en env var" — no Credential Broker in this phase).
    """

    def __init__(self, *, model: str | None = None, max_tokens: int = 4096) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; ClaudeProvider needs it to call the API"
            )

        import anthropic  # lazy import: keep `anthropic` optional at module-import time

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model or os.environ.get("AIGIS_CLAUDE_MODEL", _DEFAULT_MODEL)
        self._max_tokens = max_tokens

    def propose_action(self, contract: TaskContract, state: TaskState) -> ProviderAction:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=build_system_prompt(contract),
            tools=TOOL_SCHEMAS,
            messages=build_messages(state) or [{"role": "user", "content": "Begin."}],
        )
        return parse_response(response.content)
