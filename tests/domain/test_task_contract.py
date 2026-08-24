import pytest
from pydantic import ValidationError

from aigis.domain import RiskLevel, TaskContract


def test_valid_contract_is_accepted(contract: TaskContract) -> None:
    assert contract.task_id == "T01"
    assert contract.risk_level == RiskLevel.LOW
    assert contract.contract_version == "1.0"


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_iterations", 0),
        ("max_runtime_seconds", 0),
        ("max_tool_calls", 0),
        ("max_files_changed", 0),
        ("max_iterations", -1),
    ],
)
def test_limits_must_be_positive(field: str, value: int) -> None:
    kwargs = dict(
        task_id="T01",
        description="d",
        allowed_paths=["src/"],
        success_criteria=["ok"],
        required_gates=["pytest"],
        max_iterations=5,
        max_runtime_seconds=300,
        max_tool_calls=20,
        max_files_changed=3,
    )
    kwargs[field] = value
    with pytest.raises(ValidationError):
        TaskContract(**kwargs)


def test_allowed_paths_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        TaskContract(
            task_id="T01",
            description="d",
            allowed_paths=[],
            success_criteria=["ok"],
            required_gates=["pytest"],
            max_iterations=5,
            max_runtime_seconds=300,
            max_tool_calls=20,
            max_files_changed=3,
        )


def test_path_cannot_be_both_allowed_and_forbidden() -> None:
    with pytest.raises(ValidationError, match="both allowed and forbidden"):
        TaskContract(
            task_id="T01",
            description="d",
            allowed_paths=["src/", "src/aigis/policy/"],
            forbidden_paths=["src/aigis/policy/"],
            success_criteria=["ok"],
            required_gates=["pytest"],
            max_iterations=5,
            max_runtime_seconds=300,
            max_tool_calls=20,
            max_files_changed=3,
        )


def test_contract_is_frozen(contract: TaskContract) -> None:
    with pytest.raises(ValidationError):
        contract.max_iterations = 100
