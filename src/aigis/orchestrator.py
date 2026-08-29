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

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from aigis.agent.runtime import AgentRuntime
from aigis.domain import Decision, EnvironmentMetadata, Evidence, TaskContract, TaskState
from aigis.evaluation.decision_engine import DecisionEngine
from aigis.evaluation.gates import PytestGate, QualityGate, RuffGate
from aigis.evidence.bundle import EvidenceBundleWriter
from aigis.policy.engine import PolicyEngine
from aigis.policy.executor import SandboxedToolExecutor
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
) -> tuple[TaskState, Decision, Evidence]:
    """Runs one task end to end and returns ``(state, decision, evidence)``.

    Only gates named in ``contract.required_gates`` actually run — a task
    that doesn't require ``ruff`` shouldn't pay for it (or have it show up
    as a spurious NEEDS_HUMAN for a gate nobody asked for; see
    ``DecisionEngine``'s handling of missing required gates).
    """
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"

    sandbox: Sandbox = sandbox_factory(base_repo)
    sandbox.create()
    try:
        executor = SandboxedToolExecutor(PolicyEngine(contract), sandbox)
        runtime = AgentRuntime(contract, provider, executor)
        state = TaskState(run_id=run_id, task_id=contract.task_id)
        runtime.run(state)

        gate_results = [
            gate.run(sandbox) for gate in gates if gate.gate_name in contract.required_gates
        ]
        diff = sandbox.collect_diff()
    finally:
        sandbox.destroy()

    # Duck-typed and optional on purpose: only ClaudeProvider (so far) meters
    # itself this way. A ScriptedProvider (Security Suite, orchestrator's
    # own tests) has no tokens to report, and run_task must not assume every
    # Provider implementation talks to a billed API.
    usage = getattr(provider, "usage_summary", None)

    writer = EvidenceBundleWriter(base_dir=evidence_base_dir)
    environment = EnvironmentMetadata(
        run_id=run_id,
        model_provider=model_provider,
        model=model,
        task_contract_version=contract.contract_version,
        total_input_tokens=usage["input_tokens"] if usage else None,
        total_output_tokens=usage["output_tokens"] if usage else None,
    )
    evidence = writer.write(
        run_id=run_id,
        contract=contract,
        state=state,
        gate_results=gate_results,
        environment=environment,
        diff=diff,
    )

    decision = DecisionEngine().decide(
        run_id=run_id, contract=contract, state=state, gate_results=gate_results
    )
    writer.write_decision(run_id, decision)

    return state, decision, evidence


__all__ = ["DEFAULT_GATES", "run_task"]
