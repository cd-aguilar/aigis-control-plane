"""Runs one Security Evaluation Suite scenario (S01-S05) end-to-end and
writes a real Evidence Bundle for it, via the same EvidenceBundleWriter
`aigis run` uses -- so `make demo-security` produces on-disk evidence
(security-report.json, events.jsonl), not just a pytest assertion.

Deliberately reuses aigis.evaluation.security_suite.run_scenario, the same
deterministic ScriptedProvider mechanism the test suite already exercises,
rather than routing through `aigis run`'s real ClaudeProvider: S01-S04
assume "the agent already decided to try the forbidden action" on purpose
(see security_suite.py's module docstring) -- whether a real LLM would
actually fall for the prompt injection is a separate, non-deterministic
question about the model, not something a reproducible demo can assert
either way.
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


def run(scenario_id: str, evidence_dir: Path) -> tuple[Path, list[Attempt]]:
    """Runs `scenario_id` in a throwaway repo and writes its Evidence
    Bundle under `evidence_dir`. Returns the bundle path and the attempts
    recorded, so the caller can report which ones got DENYed.
    """
    if scenario_id in _SCENARIOS_BY_ID:
        scenario = _SCENARIOS_BY_ID[scenario_id]()
        run_scenario = security_suite.run_scenario
    elif scenario_id in _RESOURCE_SCENARIOS_BY_ID:
        scenario = _RESOURCE_SCENARIOS_BY_ID[scenario_id]()
        run_scenario = security_suite.run_resource_exhaustion_scenario
    else:
        known = sorted({**_SCENARIOS_BY_ID, **_RESOURCE_SCENARIOS_BY_ID})
        raise SystemExit(f"unknown security scenario {scenario_id!r}, known: {known}")

    contract: TaskContract = scenario.contract
    run_id = f"sec-{scenario_id}-{uuid.uuid4().hex[:8]}"

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
    return Path(evidence.bundle_path), attempts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one Security Evaluation Suite scenario and write its Evidence Bundle"
    )
    parser.add_argument("scenario_id", help="e.g. S01")
    parser.add_argument("--evidence-dir", type=Path, default=Path("evidence"))
    args = parser.parse_args(argv)

    bundle_path, attempts = run(args.scenario_id, args.evidence_dir)
    deny_attempts = [
        a
        for a in attempts
        if a.policy_decision is not None and a.policy_decision.decision == PolicyDecisionType.DENY
    ]

    print(f"[{args.scenario_id}] evidence: {bundle_path}")
    if not deny_attempts:
        print(f"[{args.scenario_id}] WARNING: no DENY recorded -- containment did not trigger")
        return 1
    for attempt in deny_attempts:
        decision = attempt.policy_decision
        assert decision is not None
        print(
            f"[{args.scenario_id}] DENY -- {decision.request.tool.value} "
            f"{decision.request.path or decision.request.executable} -- {decision.reason}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
