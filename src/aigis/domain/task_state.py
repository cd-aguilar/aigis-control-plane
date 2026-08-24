"""TaskState — the execution-side half of the agent's (state, event) reducer.

Mutable by design (unlike the other domain models, which are frozen): this
is the one piece of data the Agent Runtime updates every iteration. Its job
in Phase 0/1 is narrow but load-bearing: answer "are we still within the
TaskContract's limits?" deterministically, so a runaway agent produces a
`FAIL (Max Iterations Exceeded)` decision instead of an infinite loop
(CLAUDE.md, "Decisiones clave" — circuit breaker).
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from aigis.domain.attempt import Attempt
from aigis.domain.enums import ExecutionOutcome
from aigis.domain.task_contract import TaskContract


class LimitExceeded(BaseModel):
    """Which specific contract limit was breached, if any."""

    limit: str
    contract_value: int
    actual_value: int


class TaskState(BaseModel):
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)

    status: ExecutionOutcome = ExecutionOutcome.RUNNING
    iteration: int = 0
    tool_calls_count: int = 0
    files_changed: set[str] = Field(default_factory=set)
    attempts: list[Attempt] = Field(default_factory=list)

    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def record_attempt(self, attempt: Attempt, *, changed_path: str | None = None) -> None:
        """Append an Attempt and update the derived counters in one step, so
        the two can never drift apart.
        """
        self.attempts.append(attempt)
        self.iteration = max(self.iteration, attempt.iteration)
        self.tool_calls_count += 1
        if changed_path is not None:
            self.files_changed.add(changed_path)
        self.updated_at = datetime.now(timezone.utc)

    def elapsed_seconds(self, *, now: datetime | None = None) -> float:
        current = now or datetime.now(timezone.utc)
        return (current - self.started_at).total_seconds()

    def exceeded_limits(
        self, contract: TaskContract, *, now: datetime | None = None
    ) -> list[LimitExceeded]:
        """Return every contract limit currently breached (empty = within
        limits). Deterministic: same (state, contract) always yields the
        same answer, independent of what the agent claims about itself.
        """
        breaches: list[LimitExceeded] = []

        if self.iteration > contract.max_iterations:
            breaches.append(
                LimitExceeded(
                    limit="max_iterations",
                    contract_value=contract.max_iterations,
                    actual_value=self.iteration,
                )
            )
        if self.tool_calls_count > contract.max_tool_calls:
            breaches.append(
                LimitExceeded(
                    limit="max_tool_calls",
                    contract_value=contract.max_tool_calls,
                    actual_value=self.tool_calls_count,
                )
            )
        if len(self.files_changed) > contract.max_files_changed:
            breaches.append(
                LimitExceeded(
                    limit="max_files_changed",
                    contract_value=contract.max_files_changed,
                    actual_value=len(self.files_changed),
                )
            )
        elapsed = int(self.elapsed_seconds(now=now))
        if elapsed > contract.max_runtime_seconds:
            breaches.append(
                LimitExceeded(
                    limit="max_runtime_seconds",
                    contract_value=contract.max_runtime_seconds,
                    actual_value=elapsed,
                )
            )
        return breaches

    def is_within_limits(self, contract: TaskContract, *, now: datetime | None = None) -> bool:
        return not self.exceeded_limits(contract, now=now)
