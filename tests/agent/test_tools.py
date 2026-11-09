import pytest
from pydantic import ValidationError

from aigis.agent.tools import TOOL_SCHEMAS, tool_request_from_call
from aigis.domain import ToolName


def test_tool_schemas_cover_exactly_the_four_tools() -> None:
    names = {schema["name"] for schema in TOOL_SCHEMAS}
    assert names == {"read_file", "patch_file", "run_tests", "run_lint"}


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


def test_run_tests_call_maps_to_tool_request() -> None:
    req = tool_request_from_call("run_tests", {"path": "tests/test_x.py::test_a"})
    assert req.tool == ToolName.RUN_TESTS
    assert req.path == "tests/test_x.py::test_a"
    assert tool_request_from_call("run_tests", {}).path is None


def test_run_lint_call_maps_to_tool_request() -> None:
    req = tool_request_from_call("run_lint", {})
    assert req.tool == ToolName.RUN_LINT


def test_run_command_is_not_a_tool() -> None:
    """P0 D1: no generic command tool is offered, and a call to one never
    becomes a ToolRequest."""
    with pytest.raises(ValueError, match="unknown tool"):
        tool_request_from_call("run_command", {"executable": "python", "args": ["-V"]})


@pytest.mark.parametrize(
    ("name", "tool_input"),
    [
        ("run_tests", {"args": ["-x"]}),
        ("run_tests", {"executable": "python"}),
        ("run_tests", {"path": "-p evil_plugin"}),
        ("run_lint", {"path": "src/"}),
        ("run_lint", {"args": ["--fix"]}),
    ],
)
def test_fixed_profile_tools_reject_free_input(name: str, tool_input: dict) -> None:
    with pytest.raises(ValidationError):
        tool_request_from_call(name, tool_input)


def test_input_keys_outside_tool_request_are_rejected() -> None:
    with pytest.raises(ValueError, match="unexpected input"):
        tool_request_from_call("run_lint", {"config": "ruff-off.toml"})


def test_unknown_tool_name_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        tool_request_from_call("delete_everything", {})


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        tool_request_from_call("read_file", {})
