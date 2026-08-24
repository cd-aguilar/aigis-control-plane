"""ToolRequest — the only shape an agent action can take before it reaches
the Policy Engine.

Per ARCHITECTURE.md section 9: the agent never gets direct system access, it
issues structured requests. Section 9 is explicit that ``run_command`` must
be ``{"executable": "pytest", "args": ["tests/"]}``, never a shell string —
this "eliminates a whole class of command injection by construction, rather
than filtering metacharacters afterward." That decision is enforced here, at
the domain layer, not left as a convention for the Policy Engine to police.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from aigis.domain.enums import ToolName

# Metacharacters that would let a single arg smuggle a second command. Their
# presence anywhere in `executable` or `args` means someone is trying to pass
# a shell string through the arg-list interface — reject it here rather than
# hoping the Policy Engine's allowlist catches every case.
_SHELL_METACHARACTERS = ("&&", "||", ";", "|", "`", "$(", "\n")


def _reject_shell_metacharacters(value: str, field_name: str) -> str:
    for token in _SHELL_METACHARACTERS:
        if token in value:
            raise ValueError(
                f"{field_name} contains shell metacharacter {token!r}; "
                "run_command takes argv, never a shell string"
            )
    return value


class ToolRequest(BaseModel):
    """A single request from the Agent Runtime to use a tool.

    Exactly one of the tool-specific field groups should be populated,
    matching ``tool``:
      - READ_FILE: ``path``
      - PATCH_FILE: ``path``, ``old_str``, ``new_str``
      - RUN_COMMAND: ``executable``, ``args``
    """

    model_config = {"frozen": True}

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool: ToolName
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # read_file / patch_file
    path: str | None = None

    # patch_file (structured str_replace edit — never a full-file rewrite,
    # per CLAUDE.md "Decisiones clave")
    old_str: str | None = None
    new_str: str | None = None

    # run_command
    executable: str | None = None
    args: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fields_match_tool(self) -> ToolRequest:
        if self.tool == ToolName.READ_FILE:
            if not self.path:
                raise ValueError("READ_FILE requires 'path'")
        elif self.tool == ToolName.PATCH_FILE:
            if not self.path:
                raise ValueError("PATCH_FILE requires 'path'")
            if self.old_str is None or self.new_str is None:
                raise ValueError("PATCH_FILE requires 'old_str' and 'new_str'")
            if self.old_str == self.new_str:
                raise ValueError("PATCH_FILE old_str and new_str must differ")
        elif self.tool == ToolName.RUN_COMMAND:
            if not self.executable:
                raise ValueError("RUN_COMMAND requires 'executable'")
            _reject_shell_metacharacters(self.executable, "executable")
            if " " in self.executable:
                raise ValueError(
                    "executable must be a single program name, not a shell "
                    "command line (got a space in it)"
                )
            for arg in self.args:
                _reject_shell_metacharacters(arg, "args entry")
        return self
