from __future__ import annotations

from pathlib import Path

from aigis.agent.provider import ClaimDone, ProposeToolRequest
from aigis.domain import FinalDecision, ToolName, ToolRequest
from aigis.evaluation.benchmark_tasks import fix_failing_test_task, materialize
from aigis.evaluation.security_suite import ScriptedProvider
from aigis.orchestrator import run_task

_FIX_CALCULATOR = ProposeToolRequest(
    tool_request=ToolRequest(
        tool=ToolName.PATCH_FILE,
        path="src/calculator.py",
        old_str="return a + b  # bug: should subtract",
        new_str="return a - b",
    )
)


def test_run_task_end_to_end_fixes_the_bug_and_passes(tmp_path: Path) -> None:
    task = fix_failing_test_task()
    materialize(task, tmp_path)
    provider = ScriptedProvider([_FIX_CALCULATOR, ClaimDone(message="Fixed the bug.")])

    state, decision, evidence = run_task(
        task.contract,
        tmp_path,
        provider,
        evidence_base_dir=tmp_path / "evidence",
        model_provider="test",
        model="scripted",
    )

    assert decision.final == FinalDecision.PASS
    assert decision.tests_pass is True
    assert decision.lint_pass is True
    assert evidence.test_report_path == "test-report.json"
    assert evidence.lint_report_path == "lint-report.json"
    assert (tmp_path / "evidence" / state.run_id / "decision.json").exists()


def test_run_task_reports_fail_when_bug_is_not_fixed(tmp_path: Path) -> None:
    task = fix_failing_test_task()
    materialize(task, tmp_path)
    provider = ScriptedProvider([ClaimDone(message="I looked at it, seems fine.")])

    _, decision, _ = run_task(
        task.contract, tmp_path, provider, evidence_base_dir=tmp_path / "evidence"
    )

    assert decision.final == FinalDecision.FAIL
    assert decision.tests_pass is False


def test_run_task_only_runs_required_gates(tmp_path: Path) -> None:
    """A contract that only requires 'pytest' must not produce a ruff
    GateResult at all -- and must not be penalized for a gate it never
    asked for.
    """
    task = fix_failing_test_task()
    materialize(task, tmp_path)
    pytest_only_contract = task.contract.model_copy(update={"required_gates": ["pytest"]})
    provider = ScriptedProvider([_FIX_CALCULATOR, ClaimDone(message="Fixed.")])

    _, decision, evidence = run_task(
        pytest_only_contract, tmp_path, provider, evidence_base_dir=tmp_path / "evidence"
    )

    assert evidence.lint_report_path is None
    assert decision.lint_pass is True  # vacuously true: nothing required it
    assert decision.final == FinalDecision.PASS


def test_run_task_denies_attempt_outside_scope(tmp_path: Path) -> None:
    task = fix_failing_test_task()
    materialize(task, tmp_path)
    provider = ScriptedProvider(
        [
            ProposeToolRequest(tool_request=ToolRequest(tool=ToolName.READ_FILE, path="README.md")),
            ClaimDone(message="Done."),
        ]
    )

    state, decision, _ = run_task(
        task.contract, tmp_path, provider, evidence_base_dir=tmp_path / "evidence"
    )

    assert state.attempts[0].outcome.value == "POLICY_BLOCKED"
    assert decision.final == FinalDecision.FAIL  # tests never got fixed either
