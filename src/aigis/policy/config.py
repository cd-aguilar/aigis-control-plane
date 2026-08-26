"""PolicyConfig — the command allowlist half of the Policy Engine's rules.

Path rules come from ``TaskContract`` (``allowed_paths`` / ``forbidden_paths``)
because scope is per-task. Command rules live here instead, in
``policy.yaml``, because which executables exist at all (pytest, ruff,
python) is a property of the deployment, not of any one task -- editable
without touching code, per ARCHITECTURE.md section 10.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_POLICY_PATH = Path(__file__).parent / "policy.yaml"


class PolicyConfig(BaseModel):
    """Deserialized ``policy.yaml``. Frozen: a running PolicyEngine should
    never have its allowlist mutated out from under it mid-run -- reload by
    constructing a new PolicyConfig instead.
    """

    model_config = {"frozen": True}

    allowed_commands: list[str] = Field(
        min_length=1,
        description="Executable names (argv[0]) the Policy Engine will ALLOW "
        "for a RUN_COMMAND request. Deny-by-default: anything else is CMD-001.",
    )


def load_policy_config(path: Path | None = None) -> PolicyConfig:
    """Load a PolicyConfig from YAML. Defaults to the bundled policy.yaml so
    ``PolicyEngine(contract)`` works out of the box; pass ``path`` to load a
    task- or environment-specific override instead.
    """
    target = path or DEFAULT_POLICY_PATH
    with open(target, encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return PolicyConfig(**raw)
