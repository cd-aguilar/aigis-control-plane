from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from aigis.agent.provider import ClaimDone, ProposeToolRequest
from aigis.domain import (
    AgentClaim,
    Attempt,
    ExecutionOutcome,
    PolicyDecision,
    PolicyDecisionType,
    RiskLevel,
    TaskContract,
    TaskState,
    ToolName,
    ToolRequest,
)
from aigis.providers.claude import build_messages, build_system_prompt, parse_response

# --- build_system_prompt -----------------------------------------------------


def test_build_system_prompt_includes_contract_fields(contract: TaskContract) -> None:
    prompt = build_system_prompt(contract)

    assert contract.task_id in prompt
    assert contract.description in prompt
    assert "src/" in prompt
    assert "src/aigis/policy/" in prompt
    assert contract.risk_level.value in prompt


def test_build_system_prompt_handles_empty_forbidden_paths() -> None:
    contract = TaskContract(
        task_id="T02",
        description="d",
        allowed_paths=["src/"],
        success_criteria=["ok"],
        required_gates=["pytest"],
        max_iterations=5,
        max_runtime_seconds=300,
        max_tool_calls=20,
        max_files_changed=3,
    )
    prompt = build_system_prompt(contract)
    assert "(none)" in prompt


# --- build_messages -----------------------------------------------------------


def test_build_messages_empty_state_is_empty_list(fresh_state: TaskState) -> None:
    assert build_messages(fresh_state) == []


def test_build_messages_reconstructs_attempt_as_tool_use_and_result(
    fresh_state: TaskState,
) -> None:
    tool_request = ToolRequest(tool=ToolName.READ_FILE, path="README.md")
    attempt = Attempt(
        iteration=1,
        tool_request=tool_request,
        outcome=ExecutionOutcome.COMPLETED,
        output="hello world",
        started_at=datetime.now(timezone.utc),
    )
    fresh_state.record_attempt(attempt)

    messages = build_messages(fresh_state)

    assert len(messages) == 2
    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"][0]["type"] == "tool_use"
    assert messages[0]["content"][0]["name"] == "read_file"
    assert messages[0]["content"][0]["input"] == {"path": "README.md"}
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["type"] == "tool_result"
    assert messages[1]["content"][0]["content"] == "hello world"
    assert messages[1]["content"][0]["is_error"] is False


def test_build_messages_marks_failed_attempt_as_error(fresh_state: TaskState) -> None:
    tool_request = ToolRequest(
        tool=ToolName.RUN_COMMAND, executable="pytest", args=["tests/"]
    )
    attempt = Attempt(
        iteration=1,
        tool_request=tool_request,
        outcome=ExecutionOutcome.FAILED,
        error="2 tests failed",
        started_at=datetime.now(timezone.utc),
    )
    fresh_state.record_attempt(attempt)

    messages = build_messages(fresh_state)

    assert messages[1]["content"][0]["is_error"] is True
    assert "2 tests failed" in messages[1]["content"][0]["content"]


def test_build_messages_surfaces_policy_denial(fresh_state: TaskState) -> None:
    tool_request = ToolRequest(
        tool=ToolName.RUN_COMMAND, executable="cat", args=["fake_secret.txt"]
    )
    decision = PolicyDecision(
        decision=PolicyDecisionType.DENY,
        policy_id="PATH-004",
        reason="outside allowed_paths",
        risk=RiskLevel.HIGH,
        request=tool_request,
    )
    attempt = Attempt(
        iteration=1,
        tool_request=tool_request,
        policy_decision=decision,
        outcome=ExecutionOutcome.POLICY_BLOCKED,
        started_at=datetime.now(timezone.utc),
    )
    fresh_state.record_attempt(attempt)

    messages = build_messages(fresh_state)

    assert "DENIED" in messages[1]["content"][0]["content"]
    assert "PATH-004" in messages[1]["content"][0]["content"]


def test_build_messages_includes_claims_as_assistant_text(fresh_state: TaskState) -> None:
    claim = AgentClaim(iteration=1, message="I believe this is done.")
    fresh_state.record_claim(claim)

    messages = build_messages(fresh_state)

    assert messages == [{"role": "assistant", "content": "I believe this is done."}]


def test_build_messages_interleaves_attempts_and_claims_in_iteration_order(
    fresh_state: TaskState,
) -> None:
    attempt = Attempt(
        iteration=1,
        tool_request=ToolRequest(tool=ToolName.READ_FILE, path="a.py"),
        outcome=ExecutionOutcome.COMPLETED,
        output="ok",
        started_at=datetime.now(timezone.utc),
    )
    fresh_state.record_attempt(attempt)
    fresh_state.record_claim(AgentClaim(iteration=2, message="Now I'm done."))

    messages = build_messages(fresh_state)

    # attempt -> [tool_use, tool_result], then the claim as one more message
    assert len(messages) == 3
    assert messages[-1] == {"role": "assistant", "content": "Now I'm done."}


# --- parse_response ------------------------------------------------------------


@dataclass
class _StubToolUseBlock:
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class _StubTextBlock:
    text: str
    type: str = "text"


def test_parse_response_with_tool_use_returns_propose_tool_request() -> None:
    action = parse_response([_StubToolUseBlock(name="read_file", input={"path": "a.py"})])

    assert isinstance(action, ProposeToolRequest)
    assert action.tool_request.tool == ToolName.READ_FILE
    assert action.tool_request.path == "a.py"


def test_parse_response_prefers_tool_use_over_accompanying_text() -> None:
    action = parse_response(
        [
            _StubTextBlock(text="I'll read the file first."),
            _StubToolUseBlock(name="read_file", input={"path": "a.py"}),
        ]
    )
    assert isinstance(action, ProposeToolRequest)


def test_parse_response_text_only_returns_claim_done() -> None:
    action = parse_response([_StubTextBlock(text="I believe the task is complete.")])

    assert isinstance(action, ClaimDone)
    assert action.message == "I believe the task is complete."


def test_parse_response_empty_blocks_returns_placeholder_claim() -> None:
    action = parse_response([])

    assert isinstance(action, ClaimDone)
    assert action.message


def test_parse_response_malformed_tool_call_raises() -> None:
    with pytest.raises(Exception):  # noqa: B017 -- ValidationError or ValueError, either is fine
        parse_response([_StubToolUseBlock(name="delete_everything", input={})])


# --- ClaudeProvider construction (no network) -----------------------------------


def test_claude_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from aigis.providers.claude import ClaudeProvider

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ClaudeProvider()
