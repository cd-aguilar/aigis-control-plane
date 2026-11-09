"""TaskContract — the boundary between human intent and agent autonomy.

Per ARCHITECTURE.md section 7: "Frontera entre la intención humana y la
autonomía del agente." This is the only place task scope, limits and success
criteria are defined. Nothing downstream (Agent Runtime, Policy Engine,
Sandbox, Decision Engine) may exceed what is declared here.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from aigis.domain.enums import RiskLevel

_ANY_DEPTH = "**/"

# 2.0 (P0 D3, 2026-11-09): protected_paths, and allowed_paths may no longer
# overlap them. Breaking: a 1.0 contract that allowed tests/ is rejected.
CONTRACT_VERSION = "2.0"

# P0 D3: the inputs a Quality Gate grades with. The agent can read them but
# never change what the gates see: the evaluation workspace always takes
# them from the base repo. Two kinds of entry:
# - a prefix ("tests/", "pytest.ini"): same rule as allowed/forbidden paths;
# - "**/<name>": that file name at ANY depth, root included.
# conftest.py is loaded by pytest wherever it sits. The ruff configs are
# by-name too, not root-only: ruff resolves the closest config per file, so
# a src/ruff.toml or src/pyproject.toml silences lint for src/ even with
# the root one untouched (checked against ruff 0.16 on 2026-11-09). The
# pytest ini files only matter at the rootdir, which the gate fixes.
DEFAULT_PROTECTED_PATHS: tuple[str, ...] = (
    "tests/",
    "**/conftest.py",
    "pytest.ini",
    ".pytest.ini",
    "setup.cfg",
    "tox.ini",
    "**/pyproject.toml",
    "**/ruff.toml",
    "**/.ruff.toml",
)


def _prefix_match(path: str, prefix: str) -> bool:
    norm_path = PurePosixPath(path)
    norm_prefix = PurePosixPath(prefix.rstrip("/") or "/")
    return norm_path == norm_prefix or norm_prefix in norm_path.parents


def path_matches_protected(path: str, entry: str) -> bool:
    """True if ``path`` is covered by one ``protected_paths`` entry.

    ``"**/conftest.py"`` matches a file named ``conftest.py`` anywhere
    (``conftest.py``, ``src/conftest.py``, ``tests/a/conftest.py``); any
    other entry is a directory/file prefix, the same rule as
    ``allowed_paths``/``forbidden_paths``.
    """
    if entry.startswith(_ANY_DEPTH):
        return PurePosixPath(path).name == entry[len(_ANY_DEPTH) :]
    return _prefix_match(path, entry)


class TaskContract(BaseModel):
    """Defines objective, scope, limits and success criteria for one run.

    The circuit-breaker limits (``max_iterations``, ``max_runtime_seconds``,
    ``max_tool_calls``, ``max_files_changed``) exist so that exceeding them
    produces a deterministic ``FAIL (Max Iterations Exceeded)`` instead of an
    agent loop that hangs indefinitely (CLAUDE.md, "Decisiones clave").
    """

    model_config = {"frozen": True}

    task_id: str = Field(min_length=1)
    description: str = Field(min_length=1)

    allowed_paths: list[str] = Field(
        min_length=1,
        description="Path prefixes/globs the agent may touch. Deny-by-default: "
        "anything not covered here is out of scope.",
    )
    forbidden_paths: list[str] = Field(
        default_factory=list,
        description="Explicit denials, checked even inside an allowed path "
        "(e.g. allow 'src/' but forbid 'src/aigis/policy/policy.yaml').",
    )
    protected_paths: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PROTECTED_PATHS),
        description="Gate inputs (tests, test/lint config): readable by the "
        "agent, never writable, and always taken from the base repo when the "
        "gates run (P0 D3). Entries are prefixes, or '**/<name>' for a file "
        "name at any depth.",
    )

    success_criteria: list[str] = Field(
        min_length=1,
        description="Human-readable, evaluable statements of what PASS means "
        "for this task. Evaluated by Quality Gates, never by the agent.",
    )
    required_gates: list[str] = Field(
        min_length=1,
        description="Gate names (e.g. ['pytest', 'ruff']) that must all pass "
        "for the Decision Engine to output PASS.",
    )

    max_iterations: int = Field(gt=0)
    max_runtime_seconds: int = Field(gt=0)
    max_tool_calls: int = Field(gt=0)
    max_files_changed: int = Field(gt=0)

    risk_level: RiskLevel = RiskLevel.LOW
    deny_escalation: Literal["security", "none"] = Field(
        default="security",
        description="P0 D6. 'security': a run that would PASS but had a "
        "security DENY (traversal/absolute path, forbidden path, patch of a "
        "protected path) becomes NEEDS_HUMAN instead. 'none': a blocked "
        "action never changes a PASS.",
    )
    contract_version: str = CONTRACT_VERSION

    @field_validator("allowed_paths", "forbidden_paths", "protected_paths")
    @classmethod
    def _no_blank_paths(cls, paths: list[str]) -> list[str]:
        if any(not p.strip() for p in paths):
            raise ValueError("paths must not be blank strings")
        return paths

    @model_validator(mode="after")
    def _forbidden_cannot_swallow_all_allowed(self) -> TaskContract:
        overlap = set(self.allowed_paths) & set(self.forbidden_paths)
        if overlap:
            raise ValueError(
                f"paths cannot be both allowed and forbidden: {sorted(overlap)}"
            )
        return self

    @model_validator(mode="after")
    def _allowed_and_protected_are_disjoint(self) -> TaskContract:
        """No allowed entry may grant write access to a protected one (P0
        D3): an allowed entry that is inside a protected prefix (or names a
        protected file), or a protected prefix that lives inside an allowed
        one (e.g. allowed '.' contains 'tests/'). A '**/<name>' entry only
        conflicts with an allowed entry that names that file itself --
        'src/' may contain a conftest.py, which simply stays protected.
        """
        conflicts = sorted(
            {
                f"{allowed!r} vs {protected!r}"
                for allowed in self.allowed_paths
                for protected in self.protected_paths
                if path_matches_protected(allowed.rstrip("/") or "/", protected)
                or (
                    not protected.startswith(_ANY_DEPTH)
                    and _prefix_match(protected.rstrip("/"), allowed)
                )
            }
        )
        if conflicts:
            raise ValueError(
                f"allowed_paths and protected_paths must not overlap: {conflicts}. "
                f"Since contract_version {CONTRACT_VERSION} (P0 D3), tests, pytest/ruff "
                "config and conftest.py are protected (read-only for the agent) by "
                "default; a 1.0 contract that allowed tests/ must allow only the code "
                "to change (e.g. 'src/')"
            )
        return self

    def is_protected(self, path: str) -> bool:
        return any(path_matches_protected(path, entry) for entry in self.protected_paths)
