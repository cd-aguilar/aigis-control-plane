import pytest

from aigis.domain import RiskLevel, TaskContract


@pytest.fixture
def contract() -> TaskContract:
    return TaskContract(
        task_id="T01",
        description="Fix failing test in tests/test_math.py",
        allowed_paths=["src/", "tests/"],
        forbidden_paths=["src/aigis/policy/"],
        success_criteria=["pytest tests/ exits 0"],
        required_gates=["pytest", "ruff"],
        max_iterations=5,
        max_runtime_seconds=300,
        max_tool_calls=20,
        max_files_changed=3,
        risk_level=RiskLevel.LOW,
    )
