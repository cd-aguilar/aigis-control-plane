from __future__ import annotations

from pathlib import Path

import pytest

from aigis.evaluation.benchmark_tasks import (
    TASKS,
    add_validation_with_decoy_task,
    materialize,
)
from aigis.evaluation.gates import PytestGate, RuffGate
from aigis.policy.engine import path_within_scope
from aigis.sandbox.local_cow import LocalCowSandbox


@pytest.mark.parametrize("task_factory", TASKS, ids=[t().task_id for t in TASKS])
def test_before_state_fails_its_own_tests(task_factory, tmp_path: Path) -> None:
    """Every task's starting point must genuinely be broken -- a fixture
    where the tests already pass would make the task meaningless.
    """
    task = task_factory()
    materialize(task, tmp_path)

    sandbox = LocalCowSandbox(tmp_path)
    sandbox.create()
    try:
        result = PytestGate().run(sandbox)
    finally:
        sandbox.destroy()

    assert result.passed is False


@pytest.mark.parametrize("task_factory", TASKS, ids=[t().task_id for t in TASKS])
def test_before_state_is_lint_clean(task_factory, tmp_path: Path) -> None:
    """The bug/stub in each task must be a behavioral one, not a style one
    -- otherwise ruff would fail for a reason unrelated to what the task
    actually asks the agent to fix.
    """
    task = task_factory()
    materialize(task, tmp_path)

    sandbox = LocalCowSandbox(tmp_path)
    sandbox.create()
    try:
        result = RuffGate().run(sandbox)
    finally:
        sandbox.destroy()

    assert result.passed is True, result.details


def test_t05_decoy_file_is_genuinely_out_of_scope() -> None:
    task = add_validation_with_decoy_task()

    assert not path_within_scope("config/secrets.env", task.contract)


def test_materialize_writes_every_setup_file(tmp_path: Path) -> None:
    task = add_validation_with_decoy_task()

    materialize(task, tmp_path)

    for relative_path in task.setup_files:
        assert (tmp_path / relative_path).exists()
