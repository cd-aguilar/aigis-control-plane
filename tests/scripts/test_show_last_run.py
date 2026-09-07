import json
import time
from pathlib import Path

import pytest
from show_last_run import find_last_run, format_summary, main


def _make_run(evidence_dir: Path, run_id: str, decision_body: str = "{}") -> Path:
    run_dir = evidence_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "decision.json").write_text(decision_body, encoding="utf-8")
    return run_dir


def test_find_last_run_picks_the_most_recently_written_decision(tmp_path: Path) -> None:
    _make_run(tmp_path, "run-older")
    time.sleep(0.01)
    newer = _make_run(tmp_path, "run-newer")

    assert find_last_run(tmp_path) == newer


def test_find_last_run_ignores_runs_without_a_decision(tmp_path: Path) -> None:
    (tmp_path / "run-incomplete").mkdir()
    completed = _make_run(tmp_path, "run-complete")

    assert find_last_run(tmp_path) == completed


def test_find_last_run_raises_when_no_run_has_a_decision(tmp_path: Path) -> None:
    (tmp_path / "run-incomplete").mkdir()

    with pytest.raises(FileNotFoundError):
        find_last_run(tmp_path)


def test_main_prints_the_decision_body(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_run(tmp_path, "run-1", decision_body='{"final": "PASS"}')

    exit_code = main(["--evidence-dir", str(tmp_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "run-1" in out
    assert '"final": "PASS"' in out


def _make_loadable_run(evidence_dir: Path, run_id: str) -> Path:
    run_dir = evidence_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "task_id": "T01",
                "iteration": 3,
                "tool_calls_count": 3,
                "started_at": "2026-01-01T00:00:00+00:00",
                "attempts": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "decision.json").write_text(json.dumps({"final": "PASS"}), encoding="utf-8")
    (run_dir / "environment.json").write_text(
        json.dumps(
            {
                "model": "claude-sonnet-5",
                "total_input_tokens": 1000,
                "total_output_tokens": 200,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_format_summary_reports_task_decision_iterations_and_cost(tmp_path: Path) -> None:
    run_dir = _make_loadable_run(tmp_path, "run-1")

    summary = format_summary(run_dir)

    assert "T01" in summary
    assert "PASS" in summary
    assert "3 iterations" in summary
    assert "$" in summary


def test_main_summary_flag_prints_the_one_liner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_loadable_run(tmp_path, "run-1")

    exit_code = main(["--evidence-dir", str(tmp_path), "--summary"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "T01" in out
    assert "PASS" in out


def test_main_fails_clearly_when_evidence_dir_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist"

    exit_code = main(["--evidence-dir", str(missing)])

    assert exit_code == 1
    assert "no evidence directory" in capsys.readouterr().err
