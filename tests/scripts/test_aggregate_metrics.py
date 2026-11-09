import json
from pathlib import Path

import pytest
from aggregate_metrics import main


def _bundle(root: Path, run_id: str, started_at: str, environment: dict) -> None:
    run = root / run_id
    run.mkdir(parents=True)
    (run / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "task_id": "T01",
                "iteration": 1,
                "tool_calls_count": 1,
                "started_at": started_at,
                "attempts": [],
            }
        ),
        encoding="utf-8",
    )
    (run / "decision.json").write_text(json.dumps({"final": "PASS"}), encoding="utf-8")
    (run / "environment.json").write_text(
        json.dumps({"model": "claude-sonnet-5", **environment}), encoding="utf-8"
    )


def test_aigis_commit_filter_separates_pre_and_post_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _bundle(tmp_path, "run-old", "2026-08-29T10:00:00Z", {})
    _bundle(
        tmp_path,
        "run-new",
        "2026-11-10T10:00:00Z",
        {"aigis_commit": "abc1234def", "aigis_dirty": False},
    )
    main(["--all", "--evidence-root", str(tmp_path), "--aigis-commit", "abc1234"])
    out = capsys.readouterr().out
    assert "filtered: 1 of 2 runs" in out
    assert "runs: 1" in out


def test_since_filter_and_empty_result_is_an_error(tmp_path: Path) -> None:
    _bundle(tmp_path, "run-old", "2026-08-29T10:00:00Z", {})
    with pytest.raises(SystemExit):
        main(["--all", "--evidence-root", str(tmp_path), "--since", "2026-11-10"])


@pytest.mark.parametrize("extra", [[], ["--per-task"]])
def test_json_output_serializes_run_provenance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str]
) -> None:
    """--json crashed after 7e697b1: RunRecord.started_at is a datetime."""
    _bundle(
        tmp_path,
        "run-new",
        "2026-11-10T10:00:00Z",
        {"aigis_commit": "abc1234def", "aigis_dirty": False},
    )
    main(["--all", "--evidence-root", str(tmp_path), "--json", *extra])
    payload = json.loads(capsys.readouterr().out)
    runs = payload["per_run"] if not extra else payload["T01"]["per_run"]
    assert runs[0]["started_at"].startswith("2026-11-10")
    assert runs[0]["aigis_commit"] == "abc1234def"
