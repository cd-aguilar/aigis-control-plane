"""TaskContract — the boundary between human intent and agent autonomy.

Per ARCHITECTURE.md section 7: "Frontera entre la intención humana y la
autonomía del agente." This is the only place task scope, limits and success
criteria are defined. Nothing downstream (Agent Runtime, Policy Engine,
Sandbox, Decision Engine) may exceed what is declared here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from aigis.domain.enums import RiskLevel


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
    contract_version: str = "1.0"

    @field_validator("allowed_paths", "forbidden_paths")
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
