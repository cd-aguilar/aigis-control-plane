"""Materializes each benchmark task (evaluation/benchmark_tasks.py) into
examples/tasks/<task_id>/ -- a real contract.json + toy repo, ready to run:

    aigis run examples/tasks/T01/contract.json examples/tasks/T01/repo

The task fixtures live in code (benchmark_tasks.py), not as static files
under examples/, so there is exactly one source of truth; this script is
how that source of truth gets materialized to disk. Regenerate after
editing a task: ``python scripts/generate_examples.py``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from aigis.evaluation.benchmark_tasks import TASKS, materialize

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "tasks"


def main() -> None:
    for factory in TASKS:
        task = factory()
        task_dir = EXAMPLES_DIR / task.task_id
        repo_dir = task_dir / "repo"
        if task_dir.exists():
            shutil.rmtree(task_dir)
        repo_dir.mkdir(parents=True)
        materialize(task, repo_dir)
        (task_dir / "contract.json").write_text(
            task.contract.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"wrote {task_dir}")


if __name__ == "__main__":
    main()
