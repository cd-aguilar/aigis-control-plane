"""PolicyConfig — the command half of the Policy Engine's rules.

Path rules come from ``TaskContract`` (``allowed_paths`` / ``forbidden_paths``
/ ``protected_paths``) because scope is per-task. Command rules live here
instead, in ``policy.yaml``, because which commands exist at all is a
property of the deployment, not of any one task -- editable without
touching code, per ARCHITECTURE.md section 10.

Since P0 D1 there are two kinds:

- ``profiles``: fixed commands (id, executable, argv, timeout) behind the
  agent's ``run_tests``/``run_lint`` tools. The agent picks a profile by
  calling the tool; it never supplies an executable or a flag.
- ``allowed_commands``: the generic ``RUN_COMMAND`` allowlist, kept for
  compatibility and empty by default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

DEFAULT_POLICY_PATH = Path(__file__).parent / "policy.yaml"

# Same rejection ToolRequest applies to run_command argv: a profile is argv,
# never a shell string.
_SHELL_METACHARACTERS = ("&&", "||", ";", "|", "`", "$(", "\n")


class CommandProfile(BaseModel):
    """One fixed command the control plane runs on the agent's behalf."""

    model_config = {"frozen": True}

    id: str = Field(min_length=1)
    executable: str = Field(min_length=1)
    argv: list[str] = Field(default_factory=list)
    default_target: str | None = Field(
        default=None,
        description="run_tests only: what pytest runs when the agent gives no path.",
    )
    timeout_seconds: int = Field(gt=0)

    @field_validator("executable")
    @classmethod
    def _single_program(cls, value: str) -> str:
        if " " in value or any(token in value for token in _SHELL_METACHARACTERS):
            raise ValueError("profile executable must be a single program name")
        return value

    @field_validator("argv")
    @classmethod
    def _no_shell_strings(cls, argv: list[str]) -> list[str]:
        for arg in argv:
            if any(token in arg for token in _SHELL_METACHARACTERS):
                raise ValueError(f"profile argv entry {arg!r} contains a shell metacharacter")
        return argv


class PolicyConfig(BaseModel):
    """Deserialized ``policy.yaml``. Frozen: a running PolicyEngine should
    never have its rules mutated out from under it mid-run -- reload by
    constructing a new PolicyConfig instead.
    """

    model_config = {"frozen": True}

    allowed_commands: list[str] = Field(
        default_factory=list,
        description="Executable names (argv[0]) the Policy Engine will ALLOW "
        "for a RUN_COMMAND request. Deny-by-default: anything else is CMD-001. "
        "Empty by default since P0 D1.",
    )
    profiles: list[CommandProfile] = Field(
        default_factory=list,
        description="Fixed commands behind run_tests/run_lint, by id. A tool "
        "whose profile is missing is DENY PROF-001.",
    )

    @field_validator("profiles")
    @classmethod
    def _unique_ids(cls, profiles: list[CommandProfile]) -> list[CommandProfile]:
        ids = [profile.id for profile in profiles]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate profile ids: {ids}")
        return profiles

    def profile(self, profile_id: str) -> CommandProfile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)


def load_policy_config(path: Path | None = None) -> PolicyConfig:
    """Load a PolicyConfig from YAML. Defaults to the bundled policy.yaml so
    ``PolicyEngine(contract)`` works out of the box; pass ``path`` to load a
    task- or environment-specific override instead.
    """
    target = path or DEFAULT_POLICY_PATH
    with open(target, encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return PolicyConfig(**raw)
