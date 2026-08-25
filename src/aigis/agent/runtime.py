"""AgentRuntime — orchestrates one task run.

Per iteration: the Provider proposes an action; if it's a tool request, the
ToolExecutor (Policy Engine + Sandbox in Phase 3) carries it out; every
outcome is folded into TaskState via reducer.py. This is the only place I/O
happens in the agent layer — it knows nothing about Claude's API shape
(providers/claude.py) or about Docker/Policy internals (Phase 3's
ToolExecutor implementation), only about the Provider and ToolExecutor
protocols. That's what lets Phase 3 plug in later with zero changes here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aigis.agent import reducer
from aigis.agent.executor import ToolExecutor
from aigis.agent.provider import ClaimDone, ProposeToolRequest, Provider
from aigis.domain import ExecutionOutcome, TaskContract, TaskState

# Hard backstop independent of the contract's own max_iterations — a bug in
# the reducer, or a misbehaving provider, must never spin forever even if
# the contract itself is misconfigured with an absurdly high limit.
ABSOLUTE_ITERATION_SAFETY_CAP = 1000


class AgentRuntime:
    def __init__(self, contract: TaskContract, provider: Provider, executor: ToolExecutor) -> None:
        self.contract = contract
        self.provider = provider
        self.executor = executor

    def step(self, state: TaskState) -> TaskState:
        """Run exactly one iteration. Mutates and returns ``state``.

        No-ops if the run is already terminal (status != RUNNING), so
        calling step() past the end of a run is always safe.
        """
        if state.status != ExecutionOutcome.RUNNING:
            return state

        if reducer.apply_circuit_breaker(self.contract, state):
            return state

        action = self.provider.propose_action(self.contract, state)

        if isinstance(action, ClaimDone):
            reducer.apply_claim_done(state, action)
            return state

        if isinstance(action, ProposeToolRequest):
            started_at = datetime.now(timezone.utc)
            result = self.executor.execute(action.tool_request)
            reducer.apply_execution_result(
                state, action.tool_request, result, started_at=started_at
            )
            return state

        raise TypeError(f"unhandled provider action: {action!r}")  # pragma: no cover

    def run(self, state: TaskState) -> TaskState:
        """Call step() until the run reaches a terminal status or the agent
        claims done, bounded by an absolute safety cap regardless of what
        the contract says.

        Reaching a claim, or the safety cap, does NOT mean the task passed —
        it only means the agent stops getting more turns. PASS/FAIL/
        NEEDS_HUMAN is the Decision Engine's call (Phase 4), made from
        evidence, never from this loop or from what the agent said.
        """
        for _ in range(ABSOLUTE_ITERATION_SAFETY_CAP):
            if state.status != ExecutionOutcome.RUNNING or state.agent_claims:
                break
            self.step(state)
        return state
