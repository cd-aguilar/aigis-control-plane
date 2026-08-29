"""CLI over ``aigis.evaluation.metrics``: prints ARCHITECTURE.md section 19
metrics for a set of real Evidence Bundles.

    python scripts/aggregate_metrics.py evidence/run-a evidence/run-b ...
    python scripts/aggregate_metrics.py --all        # every evidence/run-*
    python scripts/aggregate_metrics.py --all --json
    python scripts/aggregate_metrics.py --all --per-task   # grouped by task_id,
                                                            # meaningful once N>1 per task
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from aigis.evaluation.metrics import aggregate, aggregate_by_task, load_run


def _default_evidence_dirs(evidence_root: Path) -> list[Path]:
    return sorted(p for p in evidence_root.glob("run-*") if p.is_dir())


def _print_per_task(runs: list) -> None:
    by_task = aggregate_by_task(runs)
    print(f"{'task':<6} {'runs':>4} {'pass%':>6} {'iter':>6} {'calls':>6} {'out_tok spread':>16}")
    for task_id, agg in by_task.items():
        spread = (
            f"{agg.output_tokens_spread[0]}-{agg.output_tokens_spread[1]}"
            if agg.output_tokens_spread is not None
            else "-"
        )
        print(
            f"{task_id:<6} {agg.run_count:>4} {agg.success_rate:>6.0%} "
            f"{agg.avg_iterations:>6.1f} {agg.avg_tool_calls:>6.1f} {spread:>16}"
        )
        if agg.run_count == 1:
            print("       (single run -- spread is not evidence of anything yet)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="*", type=Path, help="evidence/<run-id> directories")
    parser.add_argument(
        "--all", action="store_true", help="use every evidence/run-* directory found"
    )
    parser.add_argument(
        "--evidence-root", type=Path, default=Path("evidence"), help="used with --all"
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--per-task",
        action="store_true",
        help="group by task_id instead of one global aggregate -- see aggregate_by_task",
    )
    args = parser.parse_args(argv)

    run_dirs = _default_evidence_dirs(args.evidence_root) if args.all else args.run_dirs
    if not run_dirs:
        parser.error("no run directories given -- pass some, or use --all")

    runs = [load_run(d) for d in run_dirs]

    if args.per_task:
        if args.json:
            payload = {
                task_id: {**asdict(agg), "per_run": [asdict(r) for r in agg.per_run]}
                for task_id, agg in aggregate_by_task(runs).items()
            }
            print(json.dumps(payload, indent=2))
        else:
            _print_per_task(runs)
        return

    metrics = aggregate(runs)

    if args.json:
        payload = asdict(metrics)
        payload["per_run"] = [asdict(r) for r in metrics.per_run]
        print(json.dumps(payload, indent=2))
        return

    print(f"runs: {metrics.run_count}")
    print(f"success rate: {metrics.success_rate:.0%}")
    print(f"avg iterations: {metrics.avg_iterations:.1f}")
    print(f"avg tool calls: {metrics.avg_tool_calls:.1f}")
    if metrics.avg_latency_seconds is not None:
        print(f"avg latency: {metrics.avg_latency_seconds:.1f}s")
    if metrics.total_cost_usd is not None:
        print(
            f"total cost: ${metrics.total_cost_usd:.4f} "
            f"({metrics.runs_with_cost_data}/{metrics.run_count} runs had token data)"
        )
    if metrics.cost_to_pass_usd is not None:
        print(f"cost-to-pass: ${metrics.cost_to_pass_usd:.4f}")
    print(f"policy DENY count: {metrics.total_policy_denies}")
    print(f"policy REQUIRE_HUMAN count: {metrics.total_policy_require_human}")
    if metrics.containment_rate is not None:
        print(f"containment rate: {metrics.containment_rate:.0%}")
    print()
    print(f"{'task':<6} {'final':<6} {'iter':>4} {'calls':>5} {'tokens_in':>9} {'tokens_out':>10}")
    for run in metrics.per_run:
        print(
            f"{run.task_id:<6} {run.final:<6} {run.iterations:>4} {run.tool_calls:>5} "
            f"{run.input_tokens if run.input_tokens is not None else '-':>9} "
            f"{run.output_tokens if run.output_tokens is not None else '-':>10}"
        )


if __name__ == "__main__":
    main()
