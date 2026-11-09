import json
from pathlib import Path

import pytest
from run_security_eval import ALL_IDS, main, run, run_with_result

from aigis.domain import PolicyDecisionType


def test_run_s01_records_a_deny_and_writes_a_security_report(tmp_path: Path) -> None:
    bundle_path, attempts = run("S01", tmp_path)

    deny = [
        a
        for a in attempts
        if a.policy_decision is not None and a.policy_decision.decision == PolicyDecisionType.DENY
    ]
    assert len(deny) == 1

    report = json.loads((bundle_path / "security-report.json").read_text(encoding="utf-8"))
    assert report["attack_blocked"] is True

    events = (bundle_path / "events.jsonl").read_text(encoding="utf-8")
    assert "DENY" in events


def test_run_unknown_scenario_raises() -> None:
    try:
        run("S99", Path("evidence"))
    except SystemExit as exc:
        assert "S99" in str(exc)
    else:
        raise AssertionError("expected SystemExit for an unknown scenario id")


def test_main_exits_zero_and_prints_deny_for_s01(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["S01", "--evidence-dir", str(tmp_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "DENY" in out


def test_all_eight_scenarios_are_runnable() -> None:
    assert ALL_IDS == ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"]


@pytest.mark.parametrize("scenario_id", ["S05", "S06", "S07", "S08"])
def test_non_s01_shapes_are_graded_by_their_own_result(scenario_id: str, tmp_path: Path) -> None:
    bundle_path, _, result = run_with_result(scenario_id, tmp_path)
    assert result.passed is True
    assert bundle_path.is_dir()


def test_decision_scenarios_write_a_full_bundle_with_decision(tmp_path: Path) -> None:
    bundle_path, _, _ = run_with_result("S07", tmp_path)
    decision = json.loads((bundle_path / "decision.json").read_text(encoding="utf-8"))
    assert decision["final"] == "FAIL"
    assert "protected_path_modified" in decision["reason"]


def test_main_all_runs_every_scenario_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["all", "--evidence-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "8/8 scenarios contained" in out
    assert "NOT CONTAINED" not in out
