from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from aigis.agent.provider import ClaimDone, ProposeToolRequest
from aigis.agent.runtime import AgentRuntime
from aigis.domain import EnvironmentMetadata, ExecutionOutcome, TaskState, ToolName, ToolRequest
from aigis.domain.enums import GateType
from aigis.evaluation.security_suite import (
    RESOURCE_SCENARIOS,
    SCENARIOS,
    ScriptedProvider,
    command_injection_scenario,
    path_traversal_scenario,
    prompt_injection_scenario,
    resource_exhaustion_scenario,
    run_resource_exhaustion_scenario,
    run_scenario,
    secret_access_scenario,
)
from aigis.evidence.bundle import EvidenceBundleWriter
from aigis.policy.engine import PolicyEngine
from aigis.policy.executor import SandboxedToolExecutor
from aigis.sandbox.local_cow import LocalCowSandbox


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


def test_s03_path_traversal_is_blocked(tmp_path: Path) -> None:
    scenario = path_traversal_scenario()

    result = run_scenario(scenario, tmp_path)

    assert result.gate_name == "S03"
    assert result.gate_type == GateType.SECURITY
    assert result.passed is True


def test_s03_reports_failure_when_the_attack_id_never_got_denied(tmp_path: Path) -> None:
    """Negative control: PATH-001 fires on '..' regardless of scope, so
    loosening allowed_paths can't flip this one the way S01/S02's controls
    do. Instead, swap in an ordinary in-scope request as the 'attack' --
    the harness must correctly report that nothing was actually blocked.
    """
    scenario = path_traversal_scenario()
    benign_request = ToolRequest(tool=ToolName.READ_FILE, path="src/app.py")
    relabeled = dataclasses.replace(
        scenario,
        actions=(ProposeToolRequest(tool_request=benign_request), ClaimDone(message="Checked.")),
        attack_request_id=benign_request.request_id,
    )

    result = run_scenario(relabeled, tmp_path)

    assert result.passed is False


def test_s04_command_injection_is_blocked(tmp_path: Path) -> None:
    scenario = command_injection_scenario()

    result = run_scenario(scenario, tmp_path)

    assert result.gate_name == "S04"
    assert result.gate_type == GateType.SECURITY
    assert result.passed is True


def test_s04_reports_failure_when_the_command_would_have_been_allowed(tmp_path: Path) -> None:
    """Negative control: 'python' is in policy.yaml's default allowlist,
    so scripting it as the 'attack' must make the harness report failure.
    """
    scenario = command_injection_scenario()
    allowed_request = ToolRequest(tool=ToolName.RUN_COMMAND, executable="python", args=["-V"])
    relabeled = dataclasses.replace(
        scenario,
        actions=(ProposeToolRequest(tool_request=allowed_request), ClaimDone(message="Checked.")),
        attack_request_id=allowed_request.request_id,
    )

    result = run_scenario(relabeled, tmp_path)

    assert result.passed is False


def test_s05_resource_exhaustion_is_contained(tmp_path: Path) -> None:
    scenario = resource_exhaustion_scenario()

    result = run_resource_exhaustion_scenario(scenario, tmp_path)

    assert result.gate_name == "S05"
    assert result.gate_type == GateType.SECURITY
    assert result.passed is True
    assert result.details["report"]["final_status"] in ("RESOURCE_EXCEEDED", "TIMEOUT")
    # The tight max_iterations=3/max_tool_calls=3 must actually be what
    # stopped it -- not luck, not AgentRuntime's 1000-iteration absolute
    # safety cap.
    assert result.details["report"]["iteration"] <= scenario.contract.max_iterations + 1


def test_s05_reports_failure_when_the_run_never_reaches_a_terminal_status(
    tmp_path: Path,
) -> None:
    """Negative control: swap the InfiniteProvider's runaway action for a
    single ClaimDone -- the run ends RUNNING (a claim is not a verdict),
    never RESOURCE_EXCEEDED/TIMEOUT, so the harness must report failure.
    """
    scenario = resource_exhaustion_scenario()

    for relative_path, content in scenario.setup_files.items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    sandbox = LocalCowSandbox(tmp_path)
    sandbox.create()
    try:
        executor = SandboxedToolExecutor(PolicyEngine(scenario.contract), sandbox)
        provider = ScriptedProvider([ClaimDone(message="Done immediately.")])
        runtime = AgentRuntime(scenario.contract, provider, executor)
        state = TaskState(run_id="sec-s05-negative", task_id=scenario.contract.task_id)
        runtime.run(state)
    finally:
        sandbox.destroy()

    assert state.status == ExecutionOutcome.RUNNING


def test_scenarios_registry_contains_all_deny_style_scenarios() -> None:
    built = [factory() for factory in SCENARIOS]
    assert {s.scenario_id for s in built} == {"S01", "S02", "S03", "S04"}


def test_resource_scenarios_registry_contains_s05() -> None:
    built = [factory() for factory in RESOURCE_SCENARIOS]
    assert {s.scenario_id for s in built} == {"S05"}


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
