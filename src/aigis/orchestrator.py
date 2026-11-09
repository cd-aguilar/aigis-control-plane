"""Orchestrator — wires the whole mechanism from ARCHITECTURE.md's central
diagram (section 1) into one call:

    TaskContract -> Agent -> ToolRequest -> Policy Engine -> Sandbox
        -> Execution -> Evidence -> Quality Gates -> Decision Engine
        -> PASS / FAIL / NEEDS_HUMAN

Every piece here (Policy Engine, Sandbox, Quality Gates, Evidence Bundle,
Decision Engine) was already built and tested in isolation through Phase 5.
This module is what Phase 6 actually adds: nothing before it ran the full
loop front to back. ``cli.py`` is a thin argument-parsing shell around
``run_task`` — kept separate so the pipeline itself is testable by calling
a plain function, without spawning a subprocess or touching argv.
"""

from __future__ import annotations

import platform
import shutil
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from aigis.agent.runtime import AgentRuntime
from aigis.domain import (
    Decision,
    EnvironmentMetadata,
    Evidence,
    GateResult,
    TaskContract,
    TaskState,
)
from aigis.domain.enums import GateType
from aigis.evaluation.decision_engine import DecisionEngine
from aigis.evaluation.gates import GateContext, PytestGate, QualityGate, RuffGate
from aigis.evidence.bundle import EvidenceBundleWriter
from aigis.policy.config import PolicyConfig
from aigis.policy.engine import PolicyEngine
from aigis.policy.executor import SandboxedToolExecutor
from aigis.provenance import aigis_commit, aigis_dirty, git_commit_of, python_version
from aigis.sandbox.docker_sandbox import SandboxImageError
from aigis.sandbox.local_cow import LocalCowSandbox

if TYPE_CHECKING:
    from aigis.agent.provider import Provider
    from aigis.sandbox.base import Sandbox

DEFAULT_GATES: tuple[QualityGate, ...] = (PytestGate(), RuffGate())


def run_task(
    contract: TaskContract,
    base_repo: Path,
    provider: Provider,
    *,
    gates: tuple[QualityGate, ...] = DEFAULT_GATES,
    sandbox_factory: type[Sandbox] = LocalCowSandbox,
    evidence_base_dir: str | Path = "evidence",
    run_id: str | None = None,
    model_provider: str = "unknown",
    model: str = "unknown",
    policy_config: PolicyConfig | None = None,
) -> tuple[TaskState, Decision, Evidence]:
    """Runs one task end to end and returns ``(state, decision, evidence)``.

    Only gates named in ``contract.required_gates`` actually run — a task
    that doesn't require ``ruff`` shouldn't pay for it (or have it show up
    as a spurious NEEDS_HUMAN for a gate nobody asked for; see
    ``DecisionEngine``'s handling of missing required gates).

    ``policy_config`` defaults to the bundled ``policy.yaml``; passing one is
    how a test checks the layers behind the Policy Engine (D2-D4) with a
    deliberately permissive policy.
    """
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    selected = [gate for gate in gates if gate.gate_name in contract.required_gates]

    sandbox: Sandbox = sandbox_factory(base_repo)
    # P0 D5: a sandbox that pins an image (DockerSandbox) must find exactly
    # that image before anything runs. Otherwise no agent turn, no gate:
    # NEEDS_HUMAN, with the reason in the bundle.
    verify_image = getattr(sandbox, "verify_image", None)
    if verify_image is not None:
        try:
            verify_image()
        except SandboxImageError as exc:
            return _sandbox_unavailable(
                contract,
                selected,
                run_id,
                evidence_base_dir,
                _environment(
                    run_id, contract, base_repo, sandbox, None, model_provider, model, None
                ),
                str(exc),
            )

    # D3 hardening: gates that compare against the base (PytestGate's
    # skip/xfail/xpass rule) take their baseline now, in a separate clean
    # copy of the base, before the agent exists. Neither the agent nor its
    # code ever runs in that copy, and base tests that write files cannot
    # show up as the agent's changes.
    contexts: dict[str, GateContext] = {}
    for gate in selected:
        collect = getattr(gate, "collect_baseline", None)
        if collect is None:
            continue
        baseline_sandbox: Sandbox = sandbox_factory(base_repo)
        baseline_sandbox.create(exclude=contract.forbidden_paths)
        try:
            contexts[gate.gate_name] = collect(baseline_sandbox)
        finally:
            baseline_sandbox.destroy()

    # P0 D2: forbidden paths are not copied into the workspace at all.
    sandbox.create(exclude=contract.forbidden_paths)
    excluded_paths = list(getattr(sandbox, "excluded_paths", []))
    try:
        policy_engine = PolicyEngine(contract, policy_config)
        executor = SandboxedToolExecutor(policy_engine, sandbox)
        runtime = AgentRuntime(contract, provider, executor)
        state = TaskState(run_id=run_id, task_id=contract.task_id)
        runtime.run(state)

        # Observed BEFORE the gates run (P0 D4): pytest/ruff leave their own
        # byproducts (caches), and those are the control plane's writes, not
        # the agent's. Must also precede start_evaluation(), which replaces
        # the agent's workspace.
        # diff.patch and observed_changes come from the same comparison.
        observed_changes = sandbox.changed_paths()
        diff = sandbox.collect_diff()

        # P0 D3: the gates never run in the agent's workspace. From here on
        # the sandbox holds the base repo plus the agent's changes outside
        # protected_paths, and every report lands in a directory outside it.
        sandbox.start_evaluation(protected=contract.protected_paths)
        discarded_changes = list(getattr(sandbox, "discarded_changes", []))
        # RuffGate lints these with --ignore-noqa. Protected paths are
        # excluded: the evaluation workspace holds their base version.
        agent_changed = tuple(
            path for path in observed_changes if not contract.is_protected(path)
        )
        report_dir = Path(tempfile.mkdtemp(prefix="aigis-gate-reports-"))
        try:
            gate_results = [
                gate.run(
                    sandbox,
                    report_dir=report_dir,
                    context=replace(
                        contexts.get(gate.gate_name, GateContext()),
                        agent_changed_files=agent_changed,
                    ),
                )
                for gate in selected
            ]
        finally:
            shutil.rmtree(report_dir, ignore_errors=True)
    finally:
        sandbox.destroy()

    # Duck-typed and optional on purpose: only ClaudeProvider (so far) meters
    # itself this way. A ScriptedProvider (Security Suite, orchestrator's
    # own tests) has no tokens to report, and run_task must not assume every
    # Provider implementation talks to a billed API.
    usage = getattr(provider, "usage_summary", None)

    writer = EvidenceBundleWriter(base_dir=evidence_base_dir)
    environment = _environment(
        run_id,
        contract,
        base_repo,
        sandbox,
        policy_engine.policy_version,
        model_provider,
        model,
        usage,
    )
    evidence = writer.write(
        run_id=run_id,
        contract=contract,
        state=state,
        gate_results=gate_results,
        environment=environment,
        diff=diff,
        observed_changes=observed_changes,
        excluded_paths=excluded_paths,
        discarded_changes=discarded_changes,
    )

    decision = DecisionEngine().decide(
        run_id=run_id,
        contract=contract,
        state=state,
        gate_results=gate_results,
        observed_changes=observed_changes,
    )
    decision = _with_isolation_note(decision, environment)
    writer.write_decision(run_id, decision)

    return state, decision, evidence


_UNSAFE_LOCAL_NOTE = (
    "; isolation: none (--unsafe-local: the agent's code ran with the host "
    "filesystem and the network visible)"
)


def _with_isolation_note(decision: Decision, environment: EnvironmentMetadata) -> Decision:
    """P0 D5: a run outside docker says so in its own verdict, not only in
    environment.json -- whatever the verdict is."""
    if environment.isolation != "none":
        return decision
    return decision.model_copy(update={"reason": decision.reason + _UNSAFE_LOCAL_NOTE})


def _environment(
    run_id: str,
    contract: TaskContract,
    base_repo: Path,
    sandbox: Sandbox,
    policy_version: str | None,
    model_provider: str,
    model: str,
    usage: dict | None,
) -> EnvironmentMetadata:
    """environment.json, with the P0 D5 provenance fields."""
    return EnvironmentMetadata(
        run_id=run_id,
        model_provider=model_provider,
        model=model,
        task_contract_version=contract.contract_version,
        policy_version=policy_version,
        isolation=getattr(sandbox, "isolation", None),
        sandbox_image=getattr(sandbox, "image", None),
        sandbox_image_digest=getattr(sandbox, "image_id", None),
        task_repo_commit=git_commit_of(Path(base_repo)),
        aigis_commit=aigis_commit(),
        aigis_dirty=aigis_dirty(),
        python_version=python_version(),
        host_platform=platform.platform(),
        total_input_tokens=usage["input_tokens"] if usage else None,
        total_output_tokens=usage["output_tokens"] if usage else None,
    )


def _sandbox_unavailable(
    contract: TaskContract,
    selected: list[QualityGate],
    run_id: str,
    evidence_base_dir: str | Path,
    environment: EnvironmentMetadata,
    reason: str,
) -> tuple[TaskState, Decision, Evidence]:
    """The sandbox cannot be trusted to run anything (P0 D5: image missing
    or not the recorded one). Every required gate gets an
    infrastructure_error, so the Decision Engine's own fail-closed rule
    yields NEEDS_HUMAN -- the same path as a gate that could not run."""
    gate_types = {gate.gate_name: gate.gate_type for gate in selected}
    gate_results = [
        GateResult(
            gate_name=name,
            gate_type=gate_types.get(name, GateType.TEST),
            passed=False,
            infrastructure_error=f"sandbox_unavailable: {reason}",
        )
        for name in contract.required_gates
    ]
    state = TaskState(run_id=run_id, task_id=contract.task_id)
    writer = EvidenceBundleWriter(base_dir=evidence_base_dir)
    evidence = writer.write(
        run_id=run_id,
        contract=contract,
        state=state,
        gate_results=gate_results,
        environment=environment,
        diff="",
        observed_changes=[],
    )
    decision = DecisionEngine().decide(
        run_id=run_id,
        contract=contract,
        state=state,
        gate_results=gate_results,
        observed_changes=[],
    )
    writer.write_decision(run_id, decision)
    return state, decision, evidence


__all__ = ["DEFAULT_GATES", "run_task"]
