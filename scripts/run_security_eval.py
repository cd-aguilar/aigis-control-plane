"""Runs Security Evaluation Suite scenarios (S01-S08) end-to-end and writes
a real Evidence Bundle for each, via the same EvidenceBundleWriter `aigis
run` uses -- so `make demo-security` produces on-disk evidence
(security-report.json, events.jsonl, decision.json), not just a pytest
assertion.

Deliberately reuses aigis.evaluation.security_suite, the same deterministic
ScriptedProvider mechanism the test suite already exercises, rather than
routing through `aigis run`'s real ClaudeProvider: the scenarios assume
"the agent already decided to try the forbidden action" on purpose (see
security_suite.py's module docstring) -- whether a real LLM would actually
fall for the prompt injection is a separate, non-deterministic question
about the model, not something a reproducible demo can assert either way.

Three scenario shapes, each graded by its own GateResult:
- S01-S04, S06: the attack request must be DENYed;
- S05: the contract's circuit breaker must end a runaway agent;
- S07, S08: the whole run_task pipeline must end in the expected Decision.

`run_security_eval.py all` runs S01-S08 and exits non-zero if any fails.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import uuid
from pathlib import Path

from aigis.domain import Attempt, EnvironmentMetadata, PolicyDecisionType, TaskContract, TaskState
from aigis.domain.quality_gate import GateResult
from aigis.evaluation import security_suite
from aigis.evidence.bundle import EvidenceBundleWriter

_SCENARIOS_BY_ID = {factory().scenario_id: factory for factory in security_suite.SCENARIOS}
_RESOURCE_SCENARIOS_BY_ID = {
    factory().scenario_id: factory for factory in security_suite.RESOURCE_SCENARIOS
}
_DECISION_SCENARIOS_BY_ID = {
    factory().scenario_id: factory for factory in security_suite.DECISION_SCENARIOS
}
ALL_IDS = sorted({**_SCENARIOS_BY_ID, **_RESOURCE_SCENARIOS_BY_ID, **_DECISION_SCENARIOS_BY_ID})


def run_with_result(
    scenario_id: str, evidence_dir: Path
) -> tuple[Path, list[Attempt], GateResult]:
    """Runs `scenario_id` in a throwaway repo and writes its Evidence
    Bundle under `evidence_dir`. Returns the bundle path, the attempts
    recorded and the scenario's own grade.
    """
    run_id = f"sec-{scenario_id}-{uuid.uuid4().hex[:8]}"

    if scenario_id in _DECISION_SCENARIOS_BY_ID:
        # S07/S08 go through run_task, which writes the full bundle itself
        # (decision.json included).
        scenario = _DECISION_SCENARIOS_BY_ID[scenario_id]()
        with tempfile.TemporaryDirectory(prefix=f"aigis-{scenario_id}-") as tmp:
            result = security_suite.run_decision_scenario(
                scenario, Path(tmp), evidence_dir=evidence_dir, run_id=run_id
            )
        attempts = [Attempt.model_validate(a) for a in result.details["report"]["attempts"]]
        return evidence_dir / run_id, attempts, result

    if scenario_id in _SCENARIOS_BY_ID:
        scenario = _SCENARIOS_BY_ID[scenario_id]()
        run_scenario = security_suite.run_scenario
    elif scenario_id in _RESOURCE_SCENARIOS_BY_ID:
        scenario = _RESOURCE_SCENARIOS_BY_ID[scenario_id]()
        run_scenario = security_suite.run_resource_exhaustion_scenario
    else:
        raise SystemExit(f"unknown security scenario {scenario_id!r}, known: {ALL_IDS}")

    contract: TaskContract = scenario.contract
    with tempfile.TemporaryDirectory(prefix=f"aigis-{scenario_id}-") as tmp:
        gate_result: GateResult = run_scenario(scenario, Path(tmp))

    report = gate_result.details["report"]
    attempts = [Attempt.model_validate(a) for a in report.get("attempts", [])]
    state = TaskState(run_id=run_id, task_id=contract.task_id, attempts=attempts)

    writer = EvidenceBundleWriter(base_dir=evidence_dir)
    environment = EnvironmentMetadata(
        run_id=run_id,
        model_provider="scripted",
        model="scripted-provider",
        task_contract_version=contract.contract_version,
    )
    evidence = writer.write(
        run_id=run_id,
        contract=contract,
        state=state,
        gate_results=[gate_result],
        environment=environment,
        diff="",
    )
    return Path(evidence.bundle_path), attempts, gate_result


def run(scenario_id: str, evidence_dir: Path) -> tuple[Path, list[Attempt]]:
    bundle_path, attempts, _ = run_with_result(scenario_id, evidence_dir)
    return bundle_path, attempts


def _report_one(scenario_id: str, evidence_dir: Path) -> bool:
    bundle_path, attempts, result = run_with_result(scenario_id, evidence_dir)
    print(f"[{scenario_id}] evidence: {bundle_path}")
    for attempt in attempts:
        decision = attempt.policy_decision
        if decision is None or decision.decision != PolicyDecisionType.DENY:
            continue
        target = decision.request.path or decision.request.executable or ""
        print(
            f"[{scenario_id}] DENY -- {decision.request.tool.value} {target} -- {decision.reason}"
        )
    report = result.details.get("report", {})
    if "decision" in report:
        print(f"[{scenario_id}] decision: {report['decision']} -- {report['decision_reason']}")
    if "final_status" in report:
        print(f"[{scenario_id}] run ended: {report['final_status']}")
    verdict = "contained" if result.passed else "NOT CONTAINED"
    print(f"[{scenario_id}] {verdict}")
    return result.passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Security Evaluation Suite scenarios and write their Evidence Bundles"
    )
    parser.add_argument("scenario_id", help=f"one of {ALL_IDS}, or 'all'")
    parser.add_argument("--evidence-dir", type=Path, default=Path("evidence"))
    args = parser.parse_args(argv)

    ids = ALL_IDS if args.scenario_id == "all" else [args.scenario_id]
    failed = [sid for sid in ids if not _report_one(sid, args.evidence_dir)]
    if len(ids) > 1:
        print(f"\n{len(ids) - len(failed)}/{len(ids)} scenarios contained", end="")
        print(f" -- NOT contained: {failed}" if failed else "")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
