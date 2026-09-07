import json
from pathlib import Path

import pytest
from run_security_eval import main, run

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
