"""Tool schemas exposed to the LLM, and the mapping from a raw tool call back
into our domain ToolRequest.

Four tools exist: ``read_file``, ``patch_file`` (structured str_replace,
never a full-file rewrite), ``run_tests`` and ``run_lint``. The last two
run a fixed profile from ``policy.yaml`` (P0 D1): no executable, no flags;
``run_tests`` only takes an optional ``path``. There is no generic command
tool -- ``run_command`` is not offered and a call to it is rejected here,
before it can become a ToolRequest.

Whatever the LLM sends still has to pass ToolRequest's own validators
(path required, old_str != new_str, no stray fields on run_tests/run_lint,
...) before it becomes a real ToolRequest. This module does not duplicate
that logic: it maps names, forwards every field the model sent (so a stray
``args`` reaches the validator and is rejected, instead of being silently
dropped) and rejects keys that are not ToolRequest fields at all.
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

RUN_TESTS_SCHEMA: dict[str, Any] = {
    "name": "run_tests",
    "description": (
        "Run the project's test suite with pytest (a fixed profile: you cannot "
        "pass flags). Returns counts, the failing test ids and their assertion "
        "messages. Optionally narrow the run with 'path': a test file, directory "
        "or node id inside the allowed or protected paths, e.g. "
        "'tests/test_calculator.py' or 'tests/test_calculator.py::test_subtract'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional test file, directory or node id.",
            },
        },
        "additionalProperties": False,
    },
}

RUN_LINT_SCHEMA: dict[str, Any] = {
    "name": "run_lint",
    "description": (
        "Run the linter (ruff check, a fixed profile) on the repo. Returns the "
        "violations as data: path, line, rule code and message. Takes no input."
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    READ_FILE_SCHEMA,
    PATCH_FILE_SCHEMA,
    RUN_TESTS_SCHEMA,
    RUN_LINT_SCHEMA,
]

_NAME_TO_TOOL: dict[str, ToolName] = {
    "read_file": ToolName.READ_FILE,
    "patch_file": ToolName.PATCH_FILE,
    "run_tests": ToolName.RUN_TESTS,
    "run_lint": ToolName.RUN_LINT,
}

# What a model may put in a tool call's input: ToolRequest's own fields,
# minus the ones the control plane sets itself.
_FORWARDABLE_FIELDS = frozenset({"path", "old_str", "new_str", "executable", "args"})


def tool_request_from_call(name: str, tool_input: dict[str, Any]) -> ToolRequest:
    """Turn a raw ``(name, input)`` tool call — from Claude or any future
    provider — into a validated ToolRequest.

    Raises ``ValueError`` for an unknown tool name (``run_command``
    included) or an input key that is not a ToolRequest field, and lets
    ``pydantic.ValidationError`` (from ToolRequest's own validators) surface
    for anything malformed -- e.g. ``args`` on ``run_tests``.
    """
    if name not in _NAME_TO_TOOL:
        raise ValueError(f"unknown tool: {name!r}; only {sorted(_NAME_TO_TOOL)} exist")

    unknown = sorted(set(tool_input) - _FORWARDABLE_FIELDS)
    if unknown:
        raise ValueError(f"unexpected input for {name!r}: {unknown}")

    kwargs: dict[str, Any] = {"tool": _NAME_TO_TOOL[name], **tool_input}
    if kwargs.get("args") is None:
        kwargs.pop("args", None)
    return ToolRequest(**kwargs)
