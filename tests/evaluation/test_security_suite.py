from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from aigis.domain import EnvironmentMetadata, TaskState
from aigis.domain.enums import GateType
from aigis.evaluation.security_suite import (
    SCENARIOS,
    prompt_injection_scenario,
    run_scenario,
    secret_access_scenario,
)
from aigis.evidence.bundle import EvidenceBundleWriter


def test_s01_prompt_injection_is_blocked(tmp_path: Path) -> None:
    scenario = prompt_injection_scenario()

    result = run_scenario(scenario, tmp_path)

    assert result.gate_name == "S01"
    assert result.gate_type == GateType.SECURITY
    assert result.passed is True
    assert result.details["report"]["attack_blocked"] is True
    # The README read (in scope) and the attack attempt (out of scope) both
    # happened -- the scenario proves the second one was actually stopped,
    # not just that the agent never tried.
    assert len(result.details["report"]["attempts"]) == 2


def test_s02_secret_access_is_blocked(tmp_path: Path) -> None:
    scenario = secret_access_scenario()

    result = run_scenario(scenario, tmp_path)

    assert result.gate_name == "S02"
    assert result.gate_type == GateType.SECURITY
    assert result.passed is True
    assert len(result.details["report"]["attempts"]) == 1


def test_s01_reports_failure_when_policy_would_have_allowed_the_attack(
    tmp_path: Path,
) -> None:
    """Negative control: if the contract's own scope had allowed the
    'attack' path, the Policy Engine would ALLOW it and the scenario must
    report passed=False -- proving this harness can actually fail, not just
    that it happens to pass against the real, correctly-scoped contract.
    """
    scenario = prompt_injection_scenario()
    permissive_contract = scenario.contract.model_copy(
        update={"allowed_paths": ["README.md", "src/"], "forbidden_paths": []}
    )
    permissive_scenario = dataclasses.replace(scenario, contract=permissive_contract)

    result = run_scenario(permissive_scenario, tmp_path)

    assert result.passed is False
    assert result.details["report"]["attack_blocked"] is False


def test_s02_reports_failure_when_secret_path_is_in_scope(tmp_path: Path) -> None:
    scenario = secret_access_scenario()
    permissive_contract = scenario.contract.model_copy(update={"allowed_paths": ["src/", ".env"]})
    permissive_scenario = dataclasses.replace(scenario, contract=permissive_contract)

    result = run_scenario(permissive_scenario, tmp_path)

    assert result.passed is False


def test_scenarios_registry_contains_both_initial_scenarios() -> None:
    built = [factory() for factory in SCENARIOS]
    assert {s.scenario_id for s in built} == {"S01", "S02"}


def test_setup_files_are_written_into_the_toy_repo_before_the_run(tmp_path: Path) -> None:
    scenario = secret_access_scenario()

    run_scenario(scenario, tmp_path)

    assert (tmp_path / ".env").exists()
    assert "API_KEY" in (tmp_path / ".env").read_text()


def test_security_gate_result_plugs_into_the_evidence_bundle(tmp_path: Path) -> None:
    """A security scenario's GateResult must be indistinguishable, to
    EvidenceBundleWriter, from a pytest/ruff one -- same 'report' details
    key, same persistence into <gate>-report.json.
    """
    repo_dir = tmp_path / "toy-repo"
    repo_dir.mkdir()
    scenario = secret_access_scenario()
    gate_result = run_scenario(scenario, repo_dir)

    writer = EvidenceBundleWriter(base_dir=tmp_path / "evidence")
    state = TaskState(run_id="sec-s02", task_id=scenario.contract.task_id)
    evidence = writer.write(
        run_id="sec-s02",
        contract=scenario.contract,
        state=state,
        gate_results=[gate_result],
        environment=EnvironmentMetadata(
            run_id="sec-s02", model_provider="n/a", model="scripted"
        ),
        diff="",
    )

    assert evidence.security_report_path == "security-report.json"
    written = json.loads((tmp_path / "evidence" / "sec-s02" / "security-report.json").read_text())
    assert written["attack_blocked"] is True
