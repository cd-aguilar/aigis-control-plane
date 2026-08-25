"""The Agent Runtime's core state-transition logic — isolated from I/O.

Per ARCHITECTURE.md section 8, the Agent Runtime is conceptually
``(state, event) -> new_state``. TaskState (Phase 0/1) is deliberately
mutable, so this module doesn't pretend to be a pure-functional reducer that
returns a fresh object each time — instead it's the one place these three
state transitions are defined, each with zero network/filesystem access, so
every branch is unit-testable without a real Provider or ToolExecutor.
``AgentRuntime`` (runtime.py) is the thin, side-effecting shell that calls
the Provider/ToolExecutor and hands their output to these functions.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aigis.agent.executor import ExecutionResult
from aigis.agent.provider import ClaimDone
from aigis.domain import AgentClaim, Attempt, ExecutionOutcome, TaskContract, TaskState, ToolRequest


def apply_circuit_breaker(contract: TaskContract, state: TaskState) -> bool:
    """Check contract limits and, if breached, set ``state.status`` to a
    terminal ExecutionOutcome. Returns True if the run must stop.

    CLAUDE.md "Decisiones clave": exceeding a limit produces a deterministic
    ``FAIL (Max Iterations Exceeded)``-shaped outcome, never a hang. There is
    no dedicated "max iterations exceeded" member on ExecutionOutcome, so a
    runtime-limit breach maps to TIMEOUT and every other limit (iterations,
    tool calls, files changed) maps to RESOURCE_EXCEEDED.
    """
    breaches = state.exceeded_limits(contract)
    if not breaches:
        return False
    state.status = (
        ExecutionOutcome.TIMEOUT
        if any(b.limit == "max_runtime_seconds" for b in breaches)
        else ExecutionOutcome.RESOURCE_EXCEEDED
    )
    state.updated_at = datetime.now(timezone.utc)
    return True


def apply_claim_done(state: TaskState, action: ClaimDone) -> AgentClaim:
    """Fold a ClaimDone provider action into state.

    Deliberately does NOT set ``state.status`` — the agent claiming done has
    no authority over the run's outcome (project thesis). The caller
    (AgentRuntime.run) stops handing the agent more iterations once a claim
    exists, but that is a scheduling decision, not a verdict.
    """
    claim = AgentClaim(iteration=state.iteration + 1, message=action.message)
    state.record_claim(claim)
    return claim


def apply_execution_result(
    state: TaskState,
    tool_request: ToolRequest,
    result: ExecutionResult,
    *,
    started_at: datetime,
) -> Attempt:
    """Fold an executed (or policy-denied) ToolRequest into state as an
    Attempt.
    """
    attempt = Attempt(
        iteration=state.iteration + 1,
        tool_request=tool_request,
        policy_decision=result.policy_decision,
        outcome=result.outcome,
        output=result.output,
        error=result.error,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )
    state.record_attempt(attempt, changed_path=result.changed_path)
    return attempt
