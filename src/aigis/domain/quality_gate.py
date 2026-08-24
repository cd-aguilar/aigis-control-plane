"""GateResult — the outcome of one deterministic Quality Gate.

Per ARCHITECTURE.md section 12: gates rely on structured output (e.g.
pytest-json-report) rather than regex over stdout, "evita que un gate
supuestamente determinista dependa de interpretar texto libre." ``details``
is meant to hold that structured report (or a reference to it), not a
free-text summary the gate wrote about itself.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from aigis.domain.enums import GateType


class GateResult(BaseModel):
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
