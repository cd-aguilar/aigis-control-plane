import pytest
from pydantic import ValidationError

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


# --- EnvironmentMetadata token usage (section 19: "token cost", "cost-to-pass") --


def test_environment_metadata_token_fields_default_to_none() -> None:
    environment = EnvironmentMetadata(run_id="r1", model_provider="n/a", model="scripted")

    assert environment.total_input_tokens is None
    assert environment.total_output_tokens is None


def test_environment_metadata_accepts_real_token_counts() -> None:
    environment = EnvironmentMetadata(
        run_id="r1",
        model_provider="anthropic",
        model="claude-sonnet-5",
        total_input_tokens=1200,
        total_output_tokens=340,
    )

    assert environment.total_input_tokens == 1200
    assert environment.total_output_tokens == 340


def test_environment_metadata_rejects_negative_token_counts() -> None:
    with pytest.raises(ValidationError):
        EnvironmentMetadata(
            run_id="r1", model_provider="anthropic", model="claude-sonnet-5",
            total_input_tokens=-1,
        )
