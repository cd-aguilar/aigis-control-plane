"""Finds the most recently written run under evidence/ and prints its
decision.json -- the "what did the last `aigis run` decide" helper
`make demo-task` uses, instead of hardcoding a run-id or re-parsing the
CLI's own stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aigis.evaluation.metrics import load_run


def format_summary(run_dir: Path) -> str:
    """One line reusing aigis.evaluation.metrics.load_run -- the same
    parsing `scripts/aggregate_metrics.py` uses -- instead of re-reading
    state.json/environment.json by hand here.
    """
    record = load_run(run_dir)
    cost = f"${record.cost_usd:.4f}" if record.cost_usd is not None else "n/a"
    return f"{record.task_id}: {record.final}, {record.iterations} iterations, cost {cost}"


def find_last_run(evidence_dir: Path) -> Path:
    """Returns the run directory whose decision.json was written most
    recently. Only directories with a decision.json count -- a run that
    crashed before the Decision Engine ran isn't "the last run" for this
    purpose, it's an incomplete one.
    """
    candidates = [
        d for d in evidence_dir.iterdir() if d.is_dir() and (d / "decision.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError(f"no run with a decision.json under {evidence_dir}")
    return max(candidates, key=lambda d: (d / "decision.json").stat().st_mtime)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print decision.json of the most recently decided aigis run"
    )
    parser.add_argument("--evidence-dir", type=Path, default=Path("evidence"))
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print a one-line task/decision/iterations/cost summary instead of decision.json",
    )
    args = parser.parse_args(argv)

    if not args.evidence_dir.exists():
        print(f"no evidence directory at {args.evidence_dir}", file=sys.stderr)
        return 1

    try:
        run_dir = find_last_run(args.evidence_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.summary:
        print(format_summary(run_dir))
        return 0

    print(f"run: {run_dir.name}")
    print((run_dir / "decision.json").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
