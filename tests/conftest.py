import functools
import os

import pytest

from aigis.domain import RiskLevel, TaskContract, TaskState


@pytest.fixture
def contract() -> TaskContract:
    """Shared across tests/domain and tests/agent so both layers exercise
    the same realistic TaskContract shape.
    """
    return TaskContract(
        task_id="T01",
        description="Fix failing test in tests/test_math.py",
        allowed_paths=["src/"],
        forbidden_paths=["src/aigis/policy/"],
        success_criteria=["pytest tests/ exits 0"],
        required_gates=["pytest", "ruff"],
        max_iterations=5,
        max_runtime_seconds=300,
        max_tool_calls=20,
        max_files_changed=3,
        risk_level=RiskLevel.LOW,
    )


@pytest.fixture
def fresh_state(contract: TaskContract) -> TaskState:
    return TaskState(run_id="run-1", task_id=contract.task_id)


# --- Docker (P0 D5) ---------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _docker_unavailable_reason() -> str | None:
    from aigis.sandbox.docker_sandbox import DockerSandbox, SandboxImageError

    if not DockerSandbox.is_available():
        return "Docker daemon not available"
    try:
        DockerSandbox(".").verify_image()
    except SandboxImageError as exc:
        return f"sandbox image not ready: {exc}"
    return None


@pytest.fixture
def docker_ready() -> None:
    """For tests that run real containers. Skips without a daemon or a
    verified sandbox image -- unless AIGIS_REQUIRE_DOCKER=1 (set in CI),
    where that is a failure: closing criterion 1 needs docker for real.
    """
    reason = _docker_unavailable_reason()
    if reason is None:
        return
    if os.environ.get("AIGIS_REQUIRE_DOCKER") == "1":
        pytest.fail(f"AIGIS_REQUIRE_DOCKER=1 but {reason}")
    pytest.skip(reason)
