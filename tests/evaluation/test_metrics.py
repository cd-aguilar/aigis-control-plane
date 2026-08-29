from __future__ import annotations

import json
from pathlib import Path

import pytest

from aigis.evaluation.metrics import aggregate, load_run


def _write_bundle(
    run_dir: Path,
    *,
    run_id: str,
    task_id: str,
    final: str,
    iteration: int,
    tool_calls_count: int,
    attempts: list[dict],
    started_at: str,
    input_tokens: int | None,
    output_tokens: int | None,
    model: str = "claude-sonnet-5",
) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "task_id": task_id,
                "iteration": iteration,
                "tool_calls_count": tool_calls_count,
                "started_at": started_at,
                "attempts": attempts,
            }
        )
    )
    (run_dir / "decision.json").write_text(json.dumps({"final": final}))
    (run_dir / "environment.json").write_text(
        json.dumps(
            {
                "model": model,
                "total_input_tokens": input_tokens,
                "total_output_tokens": output_tokens,
            }
        )
    )


def _attempt(finished_at: str, decision: str | None = None) -> dict:
    entry: dict = {"finished_at": finished_at}
    if decision is not None:
        entry["policy_decision"] = {"decision": decision}
    return entry


# --- load_run ------------------------------------------------------------------


def test_load_run_reads_the_three_bundle_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-a"
    _write_bundle(
        run_dir,
        run_id="run-a",
        task_id="T01",
        final="PASS",
        iteration=3,
        tool_calls_count=3,
        attempts=[_attempt("2026-08-29T00:00:10Z", "ALLOW")],
        started_at="2026-08-29T00:00:00Z",
        input_tokens=1000,
        output_tokens=200,
    )

    run = load_run(run_dir)

    assert run.run_id == "run-a"
    assert run.task_id == "T01"
    assert run.final == "PASS"
    assert run.iterations == 3
    assert run.tool_calls == 3
    assert run.latency_seconds == 10.0
    assert run.input_tokens == 1000
    assert run.output_tokens == 200


def test_load_run_counts_policy_decisions(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-b"
    _write_bundle(
        run_dir,
        run_id="run-b",
        task_id="T05",
        final="PASS",
        iteration=2,
        tool_calls_count=2,
        attempts=[
            _attempt("2026-08-29T00:00:05Z", "ALLOW"),
            _attempt("2026-08-29T00:00:06Z", "DENY"),
        ],
        started_at="2026-08-29T00:00:00Z",
        input_tokens=None,
        output_tokens=None,
    )

    run = load_run(run_dir)

    assert run.policy_denies == 1
    assert run.policy_require_human == 0
    assert run.cost_usd is None  # no token data


def test_load_run_latency_is_none_with_no_attempts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-c"
    _write_bundle(
        run_dir,
        run_id="run-c",
        task_id="T01",
        final="FAIL",
        iteration=0,
        tool_calls_count=0,
        attempts=[],
        started_at="2026-08-29T00:00:00Z",
        input_tokens=None,
        output_tokens=None,
    )

    run = load_run(run_dir)

    assert run.latency_seconds is None


def test_run_record_computes_cost_from_known_model_pricing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-d"
    _write_bundle(
        run_dir,
        run_id="run-d",
        task_id="T01",
        final="PASS",
        iteration=1,
        tool_calls_count=1,
        attempts=[_attempt("2026-08-29T00:00:01Z", "ALLOW")],
        started_at="2026-08-29T00:00:00Z",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    run = load_run(run_dir)

    # claude-sonnet-5: $3/M input + $15/M output
    assert run.cost_usd == pytest.approx(18.0)


def test_run_record_cost_is_none_for_an_unpriced_model(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-e"
    _write_bundle(
        run_dir,
        run_id="run-e",
        task_id="T01",
        final="PASS",
        iteration=1,
        tool_calls_count=1,
        attempts=[_attempt("2026-08-29T00:00:01Z", "ALLOW")],
        started_at="2026-08-29T00:00:00Z",
        input_tokens=100,
        output_tokens=100,
        model="some-future-model",
    )

    run = load_run(run_dir)

    assert run.cost_usd is None


# --- aggregate -------------------------------------------------------------------


def test_aggregate_rejects_empty_list() -> None:
    with pytest.raises(ValueError, match="at least one run"):
        aggregate([])


def test_aggregate_success_rate_and_averages(tmp_path: Path) -> None:
    dirs = []
    for i, final in enumerate(["PASS", "PASS", "FAIL"]):
        d = tmp_path / f"run-{i}"
        _write_bundle(
            d,
            run_id=f"run-{i}",
            task_id=f"T0{i + 1}",
            final=final,
            iteration=i + 1,
            tool_calls_count=i + 2,
            attempts=[_attempt("2026-08-29T00:00:05Z", "ALLOW")],
            started_at="2026-08-29T00:00:00Z",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        dirs.append(d)
    runs = [load_run(d) for d in dirs]

    metrics = aggregate(runs)

    assert metrics.run_count == 3
    assert metrics.success_rate == pytest.approx(2 / 3)
    assert metrics.avg_iterations == pytest.approx((1 + 2 + 3) / 3)
    assert metrics.avg_tool_calls == pytest.approx((2 + 3 + 4) / 3)
    assert metrics.total_cost_usd == pytest.approx(18.0 * 3)
    assert metrics.cost_to_pass_usd == pytest.approx(18.0 * 3 / 2)  # cost over PASSes only


def test_aggregate_containment_rate_is_none_when_every_attempt_was_allowed(
    tmp_path: Path,
) -> None:
    d = tmp_path / "run-a"
    _write_bundle(
        d,
        run_id="run-a",
        task_id="T01",
        final="PASS",
        iteration=1,
        tool_calls_count=1,
        attempts=[_attempt("2026-08-29T00:00:05Z", "ALLOW")],
        started_at="2026-08-29T00:00:00Z",
        input_tokens=None,
        output_tokens=None,
    )

    metrics = aggregate([load_run(d)])

    assert metrics.containment_rate is None


def test_aggregate_containment_rate_counts_deny_and_require_human(tmp_path: Path) -> None:
    d = tmp_path / "run-a"
    _write_bundle(
        d,
        run_id="run-a",
        task_id="T05",
        final="PASS",
        iteration=1,
        tool_calls_count=3,
        attempts=[
            _attempt("2026-08-29T00:00:01Z", "ALLOW"),
            _attempt("2026-08-29T00:00:02Z", "DENY"),
            _attempt("2026-08-29T00:00:03Z", "REQUIRE_HUMAN"),
        ],
        started_at="2026-08-29T00:00:00Z",
        input_tokens=None,
        output_tokens=None,
    )

    metrics = aggregate([load_run(d)])

    assert metrics.total_policy_denies == 1
    assert metrics.total_policy_require_human == 1
    assert metrics.containment_rate == pytest.approx(0.5)


def test_aggregate_handles_missing_token_data_without_crashing(tmp_path: Path) -> None:
    priced = tmp_path / "run-priced"
    unpriced = tmp_path / "run-unpriced"
    _write_bundle(
        priced,
        run_id="run-priced",
        task_id="T01",
        final="PASS",
        iteration=1,
        tool_calls_count=1,
        attempts=[_attempt("2026-08-29T00:00:01Z", "ALLOW")],
        started_at="2026-08-29T00:00:00Z",
        input_tokens=1_000_000,
        output_tokens=0,
    )
    _write_bundle(
        unpriced,
        run_id="run-unpriced",
        task_id="T02",
        final="PASS",
        iteration=1,
        tool_calls_count=1,
        attempts=[_attempt("2026-08-29T00:00:01Z", "ALLOW")],
        started_at="2026-08-29T00:00:00Z",
        input_tokens=None,
        output_tokens=None,
    )

    metrics = aggregate([load_run(priced), load_run(unpriced)])

    assert metrics.runs_with_cost_data == 1
    assert metrics.total_cost_usd == pytest.approx(3.0)
