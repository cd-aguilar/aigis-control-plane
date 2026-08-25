"""Tool schemas exposed to the LLM, and the mapping from a raw tool call back
into our domain ToolRequest.

Only three tools exist, matching ARCHITECTURE.md section 9 exactly:
``read_file``, ``patch_file`` (structured str_replace, never a full-file
rewrite), ``run_command`` (argv list, never a shell string). Whatever the
LLM sends still has to pass ToolRequest's own validators (path required,
old_str != new_str, no shell metacharacters, ...) before it becomes a real
ToolRequest — this module does not duplicate that logic, it only maps names
and lets the domain layer's own rules do the rejecting.
"""

from __future__ import annotations

from typing import Any

from aigis.domain import ToolName, ToolRequest

READ_FILE_SCHEMA: dict[str, Any] = {
    "name": "read_file",
    "description": "Read the contents of one file inside the task's allowed scope.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the repo root."},
        },
        "required": ["path"],
    },
}

PATCH_FILE_SCHEMA: dict[str, Any] = {
    "name": "patch_file",
    "description": (
        "Apply a structured str_replace edit to one file: replace exactly one "
        "occurrence of old_str with new_str. Never rewrites the whole file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_str": {
                "type": "string",
                "description": "Exact text to replace; must match exactly once.",
            },
            "new_str": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_str", "new_str"],
    },
}

RUN_COMMAND_SCHEMA: dict[str, Any] = {
    "name": "run_command",
    "description": (
        "Run an allowlisted command as an argument list — never a shell string. "
        "e.g. executable='pytest', args=['tests/']. Metacharacters such as "
        "&&, ;, | in executable or args are rejected."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "executable": {"type": "string"},
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["executable"],
    },
}

TOOL_SCHEMAS: list[dict[str, Any]] = [READ_FILE_SCHEMA, PATCH_FILE_SCHEMA, RUN_COMMAND_SCHEMA]

_NAME_TO_TOOL: dict[str, ToolName] = {
    "read_file": ToolName.READ_FILE,
    "patch_file": ToolName.PATCH_FILE,
    "run_command": ToolName.RUN_COMMAND,
}


def tool_request_from_call(name: str, tool_input: dict[str, Any]) -> ToolRequest:
    """Turn a raw ``(name, input)`` tool call — from Claude or any future
    provider — into a validated ToolRequest.

    Raises ``ValueError`` for an unknown tool name, and lets
    ``pydantic.ValidationError`` (from ToolRequest's own validators) surface
    for anything malformed, including a disguised shell string.
    """
    if name not in _NAME_TO_TOOL:
        raise ValueError(f"unknown tool: {name!r}; only {sorted(_NAME_TO_TOOL)} exist")

    tool = _NAME_TO_TOOL[name]
    kwargs: dict[str, Any] = {"tool": tool}

    if tool is ToolName.READ_FILE:
        kwargs["path"] = tool_input.get("path")
    elif tool is ToolName.PATCH_FILE:
        kwargs["path"] = tool_input.get("path")
        kwargs["old_str"] = tool_input.get("old_str")
        kwargs["new_str"] = tool_input.get("new_str")
    else:  # RUN_COMMAND
        kwargs["executable"] = tool_input.get("executable")
        kwargs["args"] = tool_input.get("args", [])

    return ToolRequest(**kwargs)
