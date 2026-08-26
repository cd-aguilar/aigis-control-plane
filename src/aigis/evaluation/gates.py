"""QualityGate — a deterministic pass/fail check run inside the Sandbox.

Per ARCHITECTURE.md section 12: gates are deterministic and rely on
structured output (``pytest-json-report``, ``ruff --output-format json``)
rather than regex over stdout — "evita que un gate supuestamente
determinista dependa de interpretar texto libre." Each gate drives the same
``Sandbox`` protocol ``policy/executor.py`` already uses, so a gate always
sees the sandboxed copy the agent worked in (CoW or Docker) — never the host
repo directly.

Gates run *after* the agent's turn is over (there is no ``ToolRequest`` /
Policy Engine involvement here — the Control Plane itself is driving the
sandbox at this point, not the agent), so ``pytest``/``ruff`` being on the
command allowlist in ``policy.yaml`` is a coincidence of least-privilege
scoping, not a dependency of this module.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from aigis.domain.enums import GateType
from aigis.domain.quality_gate import GateResult
from aigis.sandbox.base import Sandbox

_PYTEST_REPORT_FILE = ".aigis-pytest-report.json"


class QualityGate(Protocol):
    gate_name: str
    gate_type: GateType

    def run(self, sandbox: Sandbox) -> GateResult: ...


class PytestGate:
    """Runs ``pytest`` inside the sandbox and grades it from the
    ``pytest-json-report`` output, never from stdout text or the bare exit
    code alone (a report that fails to materialize is itself evidence of a
    problem, distinct from "tests ran and failed").
    """

    gate_name = "pytest"
    gate_type = GateType.TEST

    def __init__(self, *, args: list[str] | None = None, timeout_seconds: int = 120) -> None:
        self.args = args if args is not None else ["tests/"]
        self.timeout_seconds = timeout_seconds

    def run(self, sandbox: Sandbox) -> GateResult:
        result = sandbox.run_command(
            "pytest",
            [
                *self.args,
                "-q",
                "--json-report",
                f"--json-report-file={_PYTEST_REPORT_FILE}",
            ],
            timeout_seconds=self.timeout_seconds,
        )

        if result.timed_out:
            return GateResult(
                gate_name=self.gate_name,
                gate_type=self.gate_type,
                passed=False,
                details={"timed_out": True, "stderr": result.stderr},
            )

        try:
            raw_report = sandbox.read_file(_PYTEST_REPORT_FILE)
        except (FileNotFoundError, OSError):
            return GateResult(
                gate_name=self.gate_name,
                gate_type=self.gate_type,
                passed=False,
                details={
                    "error": "pytest-json-report was not produced",
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )

        report = json.loads(raw_report)
        summary = report.get("summary", {})
        passed = report.get("exitcode") == 0 and summary.get("failed", 0) == 0

        return GateResult(
            gate_name=self.gate_name,
            gate_type=self.gate_type,
            passed=passed,
            details={"report": report},
            duration_seconds=report.get("duration"),
        )


class RuffGate:
    """Runs ``ruff check`` inside the sandbox and grades it from ruff's own
    structured JSON output (``--output-format json``), never from the
    human-readable text format.
    """

    gate_name = "ruff"
    gate_type = GateType.LINT

    def __init__(self, *, args: list[str] | None = None, timeout_seconds: int = 60) -> None:
        self.args = args if args is not None else ["."]
        self.timeout_seconds = timeout_seconds

    def run(self, sandbox: Sandbox) -> GateResult:
        result = sandbox.run_command(
            "ruff",
            ["check", *self.args, "--output-format", "json"],
            timeout_seconds=self.timeout_seconds,
        )

        if result.timed_out:
            return GateResult(
                gate_name=self.gate_name,
                gate_type=self.gate_type,
                passed=False,
                details={"timed_out": True, "stderr": result.stderr},
            )

        # ruff check exits 0 (no violations) or 1 (violations found) as its
        # normal, structured outcomes; anything else means the tool itself
        # errored out before it could produce a verdict.
        if result.exit_code not in (0, 1):
            return GateResult(
                gate_name=self.gate_name,
                gate_type=self.gate_type,
                passed=False,
                details={
                    "error": "ruff exited abnormally",
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )

        violations: list[dict[str, Any]] = json.loads(result.stdout) if result.stdout else []
        report = {"violations": violations, "violation_count": len(violations)}

        return GateResult(
            gate_name=self.gate_name,
            gate_type=self.gate_type,
            passed=len(violations) == 0,
            details={"report": report},
        )


__all__ = ["QualityGate", "PytestGate", "RuffGate"]
