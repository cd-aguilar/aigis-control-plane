from aigis.domain import EnvironmentMetadata, Evidence, GateResult, GateType


def _evidence(gate_results: list[GateResult]) -> Evidence:
    return Evidence(
        run_id="r1",
        task_id="T01",
        bundle_path="evidence/r1/",
        environment=EnvironmentMetadata(
            run_id="r1", model_provider="anthropic", model="claude-sonnet-5"
        ),
        gate_results=gate_results,
    )


def test_all_gates_passed_true_when_every_gate_passes() -> None:
    evidence = _evidence(
        [
            GateResult(gate_name="pytest", gate_type=GateType.TEST, passed=True),
            GateResult(gate_name="ruff", gate_type=GateType.LINT, passed=True),
        ]
    )
    assert evidence.all_gates_passed()


def test_all_gates_passed_false_when_one_gate_fails() -> None:
    evidence = _evidence(
        [
            GateResult(gate_name="pytest", gate_type=GateType.TEST, passed=True),
            GateResult(gate_name="ruff", gate_type=GateType.LINT, passed=False),
        ]
    )
    assert not evidence.all_gates_passed()


def test_all_gates_passed_false_when_no_gates_ran() -> None:
    """Absence of evidence is not evidence of passing — an empty gate list
    must never be treated as 'nothing failed'.
    """
    evidence = _evidence([])
    assert not evidence.all_gates_passed()


def test_gate_lookup_by_name() -> None:
    evidence = _evidence(
        [GateResult(gate_name="pytest", gate_type=GateType.TEST, passed=True)]
    )
    assert evidence.gate("pytest").passed is True
    assert evidence.gate("ruff") is None
