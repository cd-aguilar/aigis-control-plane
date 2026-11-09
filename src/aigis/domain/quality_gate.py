"""GateResult — the outcome of one deterministic Quality Gate.

Per ARCHITECTURE.md section 12: gates rely on structured output (e.g.
pytest-json-report) rather than regex over stdout, "evita que un gate
supuestamente determinista dependa de interpretar texto libre." ``details``
is meant to hold that structured report (or a reference to it), not a
free-text summary the gate wrote about itself.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from aigis.domain.enums import GateType


class GateResult(BaseModel):
    """``infrastructure_error`` is set when the gate could not produce a
    verdict at all (tool or plugin missing, tool crashed before grading) --
    as opposed to a gate that ran and found failures. The Decision Engine
    turns the former into NEEDS_HUMAN (``gate_infrastructure_error``) and
    the latter into FAIL (P0 D3).
    """

    model_config = {"frozen": True}

    gate_name: str = Field(min_length=1, description="e.g. 'pytest', 'ruff'")
    gate_type: GateType
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)
    report_path: str | None = Field(
        default=None,
        description="Path within the Evidence Bundle to the structured "
        "report this result was derived from, e.g. 'test-report.json'.",
    )
    duration_seconds: float | None = Field(default=None, ge=0)
    infrastructure_error: str | None = Field(
        default=None,
        description="Why the gate could not run (no verdict). Never set "
        "together with passed=True.",
    )

    rule_violations: list[str] = Field(
        default_factory=list,
        description="Control-plane grading rules this run broke even though "
        "the tool itself may have reported success (P0 D3 hardening), e.g. "
        "'no_test_passed' or 'gate_outcome_changed: <nodeid> (passed -> "
        "skipped)'. Never set together with passed=True.",
    )

    @model_validator(mode="after")
    def _infrastructure_error_never_passes(self) -> GateResult:
        if self.infrastructure_error is not None and self.passed:
            raise ValueError("a gate with an infrastructure_error cannot have passed")
        if self.rule_violations and self.passed:
            raise ValueError("a gate with rule_violations cannot have passed")
        return self
