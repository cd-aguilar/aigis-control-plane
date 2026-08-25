import pytest
from pydantic import ValidationError

from aigis.agent.tools import TOOL_SCHEMAS, tool_request_from_call
from aigis.domain import ToolName


def test_tool_schemas_cover_exactly_the_three_tools() -> None:
    names = {schema["name"] for schema in TOOL_SCHEMAS}
    assert names == {"read_file", "patch_file", "run_command"}


def test_read_file_call_maps_to_tool_request() -> None:
    req = tool_request_from_call("read_file", {"path": "README.md"})
    assert req.tool == ToolName.READ_FILE
    assert req.path == "README.md"


def test_patch_file_call_maps_to_tool_request() -> None:
    req = tool_request_from_call(
        "patch_file", {"path": "src/x.py", "old_str": "a", "new_str": "b"}
    )
    assert req.tool == ToolName.PATCH_FILE
    assert req.old_str == "a"
    assert req.new_str == "b"


def test_run_command_call_maps_to_tool_request() -> None:
    req = tool_request_from_call(
        "run_command", {"executable": "pytest", "args": ["tests/", "-x"]}
    )
    assert req.tool == ToolName.RUN_COMMAND
    assert req.executable == "pytest"
    assert req.args == ["tests/", "-x"]


def test_run_command_call_defaults_args_to_empty_list() -> None:
    req = tool_request_from_call("run_command", {"executable": "pytest"})
    assert req.args == []


def test_unknown_tool_name_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        tool_request_from_call("delete_everything", {})


def test_malicious_run_command_input_is_still_rejected() -> None:
    """The LLM is untrusted input. Even though this module doesn't
    re-implement shell-metacharacter checks, whatever the LLM sends still
    has to pass ToolRequest's own validator (agent-independent proof that
    the injection defense is structural, not per-caller).
    """
    with pytest.raises(ValidationError):
        tool_request_from_call(
            "run_command", {"executable": "pytest", "args": ["tests/ && rm -rf /"]}
        )


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        tool_request_from_call("read_file", {})
