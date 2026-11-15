"""Materializes each benchmark task (evaluation/benchmark_tasks.py) into
examples/tasks/<task_id>/ -- a real contract.json + toy repo, ready to run:

    aigis run examples/tasks/T01/contract.json examples/tasks/T01/repo

The task fixtures live in code (benchmark_tasks.py), not as static files
under examples/, so there is exactly one source of truth; this script is
how that source of truth gets materialized to disk. Regenerate after
editing a task: ``python scripts/generate_examples.py``.

v0.2 D7/D9: each task also gets ``oracle.json`` (hidden cases) and
``solution.patch`` (reference fix) NEXT TO ``repo/``, never inside it: the
sandbox copies ``repo/`` only, so neither can reach the agent's workspace.
"""

from __future__ import annotations

import difflib
import json
import shutil
from pathlib import Path

from aigis.evaluation.benchmark_tasks import TASKS, BenchmarkTask, materialize

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "tasks"


def oracle_json(task: BenchmarkTask) -> str:
    return json.dumps(task.oracle, indent=2) + "\n"


def solution_patch(task: BenchmarkTask) -> str:
    """Unified diff (a/ b/ prefixes, ``git apply``-able) from the task's
    base files to its reference solution."""
    chunks = []
    for path in sorted(task.reference_files):
        before = task.setup_files.get(path, "")
        after = task.reference_files[path]
        chunks.append(
            "".join(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
        )
    return "".join(chunks)


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
        (task_dir / "oracle.json").write_text(oracle_json(task), encoding="utf-8")
        (task_dir / "solution.patch").write_text(solution_patch(task), encoding="utf-8")
        print(f"wrote {task_dir}")


if __name__ == "__main__":
    main()
