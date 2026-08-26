from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aigis.domain import (
    Attempt,
    Decision,
    EnvironmentMetadata,
    ExecutionOutcome,
    FinalDecision,
    GateResult,
    PolicyDecision,
    PolicyDecisionType,
    RiskLevel,
    TaskContract,
    TaskState,
    ToolName,
    ToolRequest,
)
from aigis.domain.enums import GateType
from aigis.evidence.bundle import EvidenceBundleWriter


def _environment() -> EnvironmentMetadata:
    return EnvironmentMetadata(run_id="r1", model_provider="anthropic", model="claude-x")


def _allow_attempt(path: str = "src/x.py") -> Attempt:
    request = ToolRequest(tool=ToolName.READ_FILE, path=path)
    decision = PolicyDecision(
        decision=PolicyDecisionType.ALLOW,
        policy_id="PATH-000",
        reason="within allowed_paths",
        risk=RiskLevel.LOW,
        request=request,
    )
    return Attempt(
        iteration=1,
        tool_request=request,
        policy_decision=decision,
        outcome=ExecutionOutcome.COMPLETED,
    )


def test_write_creates_every_expected_file(
    tmp_path: Path, contract: TaskContract, fresh_state: TaskState
) -> None:
    fresh_state.attempts.append(_allow_attempt())
    gate_results = [
        GateResult(
            gate_name="pytest",
            gate_type=GateType.TEST,
            passed=True,
            details={"report": {"summary": {"passed": 1, "failed": 0}}},
        ),
        GateResult(
            gate_name="ruff",
            gate_type=GateType.LINT,
            passed=True,
            details={"report": {"violation_count": 0}},
        ),
    ]
    writer = EvidenceBundleWriter(base_dir=tmp_path / "evidence")

    evidence = writer.write(
        run_id="r1",
        contract=contract,
        state=fresh_state,
        gate_results=gate_results,
        environment=_environment(),
        diff="--- a/x.py\n+++ b/x.py\n",
    )

    run_dir = tmp_path / "evidence" / "r1"
    expected_files = {
        "task.json",
        "state.json",
        "trace.jsonl",
        "events.jsonl",
        "diff.patch",
        "test-report.json",
        "lint-report.json",
        "environment.json",
        "manifest.json",
        "hashes.json",
    }
    assert expected_files == {p.name for p in run_dir.iterdir()}

    assert evidence.bundle_path == f"{run_dir.as_posix()}/"
    assert evidence.test_report_path == "test-report.json"
    assert evidence.lint_report_path == "lint-report.json"
    assert evidence.gate("pytest").report_path == "test-report.json"
    assert json.loads((run_dir / "test-report.json").read_text())["summary"]["passed"] == 1

    trace_lines = (run_dir / "trace.jsonl").read_text().splitlines()
    assert len(trace_lines) == 1
    events_lines = (run_dir / "events.jsonl").read_text().splitlines()
    assert len(events_lines) == 1
    assert json.loads(events_lines[0])["decision"] == "ALLOW"


def test_hashes_json_matches_every_other_written_file(
    tmp_path: Path, contract: TaskContract, fresh_state: TaskState
) -> None:
    writer = EvidenceBundleWriter(base_dir=tmp_path / "evidence")
    writer.write(
        run_id="r2",
        contract=contract,
        state=fresh_state,
        gate_results=[],
        environment=_environment(),
        diff="",
    )

    run_dir = tmp_path / "evidence" / "r2"
    hashes = json.loads((run_dir / "hashes.json").read_text())

    assert "hashes.json" not in hashes
    assert "decision.json" not in hashes
    for name, expected_hash in hashes.items():
        assert hashlib.sha256((run_dir / name).read_bytes()).hexdigest() == expected_hash


def test_gate_without_report_leaves_report_path_none(
    tmp_path: Path, contract: TaskContract, fresh_state: TaskState
) -> None:
    gate_results = [GateResult(gate_name="pytest", gate_type=GateType.TEST, passed=False)]
    writer = EvidenceBundleWriter(base_dir=tmp_path / "evidence")

    evidence = writer.write(
        run_id="r3",
        contract=contract,
        state=fresh_state,
        gate_results=gate_results,
        environment=_environment(),
        diff="",
    )

    assert evidence.test_report_path is None
    assert evidence.gate("pytest").report_path is None
    assert not (tmp_path / "evidence" / "r3" / "test-report.json").exists()


def test_write_decision_writes_separate_file_after_bundle(
    tmp_path: Path, contract: TaskContract, fresh_state: TaskState
) -> None:
    writer = EvidenceBundleWriter(base_dir=tmp_path / "evidence")
    writer.write(
        run_id="r4",
        contract=contract,
        state=fresh_state,
        gate_results=[],
        environment=_environment(),
        diff="",
    )
    decision = Decision(
        run_id="r4",
        task_id=contract.task_id,
        contract_valid=True,
        policy_ok=True,
        tests_pass=True,
        lint_pass=True,
        scope_ok=True,
        resource_limits_ok=True,
        final=FinalDecision.PASS,
        reason="all gates green",
    )

    filename = writer.write_decision("r4", decision)

    assert filename == "decision.json"
    written = json.loads((tmp_path / "evidence" / "r4" / "decision.json").read_text())
    assert written["final"] == "PASS"
