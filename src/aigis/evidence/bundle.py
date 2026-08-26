"""EvidenceBundleWriter — persists one run's Evidence Bundle to disk.

Per ARCHITECTURE.md section 13, the on-disk layout is:

    evidence/<run-id>/
        manifest.json  task.json  trace.jsonl  state.json  events.jsonl
        diff.patch  test-report.json  lint-report.json  security-report.json
        environment.json  hashes.json  decision.json

This module is the only place that touches the real filesystem for evidence
purposes — everything it writes comes from domain models or ``GateResult``s
that were already computed deterministically elsewhere (Policy Engine,
Sandbox, Quality Gates). JSON is dumped with sorted keys so that two runs
with identical state produce byte-identical files, which is what makes
``hashes.json`` a meaningful integrity check rather than noise.

``decision.json`` is written separately via :meth:`write_decision`, after the
Decision Engine has run — a ``Decision`` cannot exist before the rest of the
bundle does (it evaluates gate results that are already in the bundle), so
``hashes.json`` deliberately covers every artifact *except* decision.json:
hashing an artifact that would need to reference its own hash is circular,
not a integrity guarantee.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from aigis.domain import (
    Decision,
    EnvironmentMetadata,
    Evidence,
    GateResult,
    TaskContract,
    TaskState,
)
from aigis.domain.enums import GateType

_REPORT_FILENAME_BY_GATE_TYPE = {
    GateType.TEST: "test-report.json",
    GateType.LINT: "lint-report.json",
    GateType.SECURITY: "security-report.json",
}


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


class EvidenceBundleWriter:
    def __init__(self, base_dir: str | Path = "evidence") -> None:
        self.base_dir = Path(base_dir)

    def write(
        self,
        *,
        run_id: str,
        contract: TaskContract,
        state: TaskState,
        gate_results: list[GateResult],
        environment: EnvironmentMetadata,
        diff: str,
    ) -> Evidence:
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        written: list[str] = []

        def write_file(name: str, content: str) -> str:
            (run_dir / name).write_text(content, encoding="utf-8")
            written.append(name)
            return name

        task_path = write_file("task.json", contract.model_dump_json(indent=2))
        state_path = write_file("state.json", state.model_dump_json(indent=2))
        trace_path = write_file(
            "trace.jsonl",
            "\n".join(a.model_dump_json() for a in state.attempts),
        )
        events_path = write_file(
            "events.jsonl",
            "\n".join(
                a.policy_decision.model_dump_json()
                for a in state.attempts
                if a.policy_decision is not None
            ),
        )
        diff_path = write_file("diff.patch", diff)

        resolved_gates: list[GateResult] = []
        report_path_by_gate: dict[str, str] = {}
        for gate in gate_results:
            report = gate.details.get("report")
            if report is None:
                resolved_gates.append(gate)
                continue
            filename = _REPORT_FILENAME_BY_GATE_TYPE.get(
                gate.gate_type, f"{gate.gate_name}-report.json"
            )
            write_file(filename, _dump(report))
            report_path_by_gate[gate.gate_name] = filename
            resolved_gates.append(gate.model_copy(update={"report_path": filename}))

        write_file("environment.json", environment.model_dump_json(indent=2))

        manifest = {
            "run_id": run_id,
            "task_id": contract.task_id,
            "files": sorted(written),
        }
        write_file("manifest.json", _dump(manifest))

        hashes = {
            name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
            for name in written
        }
        hashes_path = write_file("hashes.json", _dump(hashes))

        return Evidence(
            run_id=run_id,
            task_id=contract.task_id,
            bundle_path=f"{run_dir.as_posix()}/",
            diff_path=diff_path,
            test_report_path=report_path_by_gate.get("pytest"),
            lint_report_path=report_path_by_gate.get("ruff"),
            security_report_path=next(
                (
                    v
                    for k, v in report_path_by_gate.items()
                    if k not in ("pytest", "ruff")
                ),
                None,
            ),
            trace_path=trace_path,
            events_path=events_path,
            state_path=state_path,
            task_path=task_path,
            hashes_path=hashes_path,
            environment=environment,
            gate_results=resolved_gates,
        )

    def write_decision(self, run_id: str, decision: Decision) -> str:
        """Writes ``decision.json`` after the Decision Engine has produced a
        verdict. Returns the path written, for the caller's own records
        (there is no ``Evidence.decision_path`` field — the Decision itself
        carries ``evidence_ref`` pointing the other way, back at the bundle).
        """
        run_dir = self.base_dir / run_id
        path = run_dir / "decision.json"
        path.write_text(decision.model_dump_json(indent=2), encoding="utf-8")
        return "decision.json"


__all__ = ["EvidenceBundleWriter"]
