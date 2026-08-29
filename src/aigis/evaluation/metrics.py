"""Aggregates ARCHITECTURE.md section 19 metrics across a set of real runs'
Evidence Bundles.

Reads only what ``EvidenceBundleWriter`` already persists (``state.json``,
``decision.json``, ``environment.json``) -- no live API calls, this never
runs a task itself. Pair with ``scripts/aggregate_metrics.py`` for the CLI
entry point.

Honest scoping (matches this project's existing "don't overclaim" pattern,
e.g. Sandbox/Security Model docstrings): a handful of runs against three
different benchmark tasks is not a statistically meaningful sample.
``cost_usd`` is priced from a hardcoded per-model table maintained here, not
looked up live, so it goes stale the moment list pricing changes --
treat it as an estimate, not a bill.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Anthropic list pricing, USD per million tokens. Update this table if it
# drifts -- it's the only place a dollar figure is hardcoded, precisely so
# there's one place to fix.
PRICE_PER_MILLION_TOKENS_USD: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
}


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    task_id: str
    final: str  # FinalDecision value: PASS / FAIL / NEEDS_HUMAN
    iterations: int
    tool_calls: int
    policy_denies: int
    policy_require_human: int
    latency_seconds: float | None
    input_tokens: int | None
    output_tokens: int | None
    model: str | None

    @property
    def cost_usd(self) -> float | None:
        if self.model is None or self.input_tokens is None or self.output_tokens is None:
            return None
        prices = PRICE_PER_MILLION_TOKENS_USD.get(self.model)
        if prices is None:
            return None
        return (self.input_tokens / 1_000_000) * prices["input"] + (
            self.output_tokens / 1_000_000
        ) * prices["output"]


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_run(run_dir: Path) -> RunRecord:
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    decision = json.loads((run_dir / "decision.json").read_text(encoding="utf-8"))
    environment = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))

    attempts = state.get("attempts", [])
    latency = None
    if attempts:
        start = _parse_timestamp(state["started_at"])
        end = _parse_timestamp(attempts[-1]["finished_at"])
        latency = (end - start).total_seconds()

    decisions = [a["policy_decision"]["decision"] for a in attempts if a.get("policy_decision")]

    return RunRecord(
        run_id=state["run_id"],
        task_id=state["task_id"],
        final=decision["final"],
        iterations=state["iteration"],
        tool_calls=state["tool_calls_count"],
        policy_denies=decisions.count("DENY"),
        policy_require_human=decisions.count("REQUIRE_HUMAN"),
        latency_seconds=latency,
        input_tokens=environment.get("total_input_tokens"),
        output_tokens=environment.get("total_output_tokens"),
        model=environment.get("model"),
    )


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class AggregateMetrics:
    run_count: int
    success_rate: float
    avg_iterations: float
    avg_tool_calls: float
    avg_latency_seconds: float | None
    total_cost_usd: float | None
    cost_to_pass_usd: float | None
    runs_with_cost_data: int
    total_policy_denies: int
    total_policy_require_human: int
    containment_rate: float | None
    per_run: list[RunRecord]


def aggregate(runs: list[RunRecord]) -> AggregateMetrics:
    """Computes section 19's metrics from a list of already-loaded runs.

    ``containment_rate`` (denied / (denied + require_human)) only means
    something when at least one non-ALLOW decision happened at all -- with
    an all-green benchmark run (every attempt ALLOWed, as intended), it's
    ``None``, not a misleading 0.0 or 1.0. Contrast with
    ``security_suite.py``, whose scenarios exist specifically to produce
    the DENY this metric is about.

    This mixes every task into a single bag -- fine for a headline "8/8,
    100%" number, but it can't tell you whether one task is consistently
    more expensive than the rest or just had one noisy run. Once there's
    more than one run per task, use ``aggregate_by_task`` for that.
    """
    if not runs:
        raise ValueError("aggregate() needs at least one run")

    passed = [r for r in runs if r.final == "PASS"]
    costs = [r.cost_usd for r in runs if r.cost_usd is not None]
    latencies = [r.latency_seconds for r in runs if r.latency_seconds is not None]
    denies = sum(r.policy_denies for r in runs)
    require_human = sum(r.policy_require_human for r in runs)
    non_allow = denies + require_human

    return AggregateMetrics(
        run_count=len(runs),
        success_rate=len(passed) / len(runs),
        avg_iterations=_avg([r.iterations for r in runs]),
        avg_tool_calls=_avg([r.tool_calls for r in runs]),
        avg_latency_seconds=_avg(latencies),
        total_cost_usd=sum(costs) if costs else None,
        cost_to_pass_usd=(sum(costs) / len(passed)) if costs and passed else None,
        runs_with_cost_data=len(costs),
        total_policy_denies=denies,
        total_policy_require_human=require_human,
        containment_rate=(denies / non_allow) if non_allow else None,
        per_run=runs,
    )


@dataclass(frozen=True)
class TaskAggregate:
    """Same shape of question as ``AggregateMetrics``, scoped to one task_id.

    Exists specifically to answer "is this task's cost/output consistently
    high, or was that one run noise?" -- a question ``aggregate()`` cannot
    answer because it collapses every task into one number. ``spread``
    reports (min, max) output_tokens across the task's runs so a one-run
    task (spread == (x, x)) is visibly not yet evidence of anything, and a
    wide spread across N>1 runs is visibly worth a closer look.
    """

    task_id: str
    run_count: int
    success_rate: float
    avg_iterations: float
    avg_tool_calls: float
    avg_latency_seconds: float | None
    avg_cost_usd: float | None
    output_tokens_spread: tuple[int, int] | None  # (min, max) across this task's runs
    per_run: list[RunRecord]


def aggregate_by_task(runs: list[RunRecord]) -> dict[str, TaskAggregate]:
    """Groups ``runs`` by ``task_id`` and computes per-task stats, keyed by
    task_id and sorted for stable, reproducible output.

    With N=1 per task (the 2026-08-29 baseline), every ``TaskAggregate``
    here is just that one run reshaped -- not more meaningful than reading
    ``per_run`` directly. The point is what happens once a second pass
    exists: two ``RunRecord``s for T06, say, turn into one ``TaskAggregate``
    with ``run_count=2`` and a real ``output_tokens_spread``, which is what
    actually distinguishes "T06 is structurally heavier" from "that one run
    was noise" -- see EVALUATION.md.
    """
    by_task: dict[str, list[RunRecord]] = defaultdict(list)
    for run in runs:
        by_task[run.task_id].append(run)

    result: dict[str, TaskAggregate] = {}
    for task_id, task_runs in sorted(by_task.items()):
        passed = [r for r in task_runs if r.final == "PASS"]
        costs = [r.cost_usd for r in task_runs if r.cost_usd is not None]
        latencies = [r.latency_seconds for r in task_runs if r.latency_seconds is not None]
        output_tokens = [r.output_tokens for r in task_runs if r.output_tokens is not None]

        result[task_id] = TaskAggregate(
            task_id=task_id,
            run_count=len(task_runs),
            success_rate=len(passed) / len(task_runs),
            avg_iterations=_avg([r.iterations for r in task_runs]),
            avg_tool_calls=_avg([r.tool_calls for r in task_runs]),
            avg_latency_seconds=_avg(latencies),
            avg_cost_usd=_avg(costs),
            output_tokens_spread=(min(output_tokens), max(output_tokens))
            if output_tokens
            else None,
            per_run=task_runs,
        )
    return result


__all__ = [
    "PRICE_PER_MILLION_TOKENS_USD",
    "RunRecord",
    "AggregateMetrics",
    "TaskAggregate",
    "load_run",
    "aggregate",
    "aggregate_by_task",
]
