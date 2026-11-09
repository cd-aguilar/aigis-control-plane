import pytest

from aigis.domain import PolicyDecisionType, RiskLevel, TaskContract, ToolName, ToolRequest
from aigis.policy.config import PolicyConfig
from aigis.policy.engine import PolicyEngine


@pytest.fixture
def config() -> PolicyConfig:
    return PolicyConfig(allowed_commands=["pytest", "ruff", "python"])


@pytest.fixture
def engine(contract: TaskContract, config: PolicyConfig) -> PolicyEngine:
    return PolicyEngine(contract, config)


# --- path rules (READ_FILE / PATCH_FILE) --------------------------------------


def test_allows_read_within_allowed_paths(engine: PolicyEngine) -> None:
    request = ToolRequest(tool=ToolName.READ_FILE, path="src/aigis/cli.py")
    decision = engine.evaluate(request)

    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.policy_id == "PATH-000"


def test_allows_read_of_exact_allowed_file(engine: PolicyEngine) -> None:
    # tests/ is not in allowed_paths since P0 D3 (allowed is "src/"), but it
    # is a protected path: readable by the agent, never patchable.
    request = ToolRequest(tool=ToolName.READ_FILE, path="tests/test_math.py")
    assert engine.evaluate(request).decision == PolicyDecisionType.ALLOW


@pytest.mark.parametrize("path", ["tests/test_math.py", "src/conftest.py", "pyproject.toml"])
def test_protected_paths_are_read_only(engine: PolicyEngine, path: str) -> None:
    """P0 D3: a protected path can be read even outside allowed_paths, and
    can never be patched -- not even src/conftest.py, which "src/" covers.
    """
    read = engine.evaluate(ToolRequest(tool=ToolName.READ_FILE, path=path))
    patch = engine.evaluate(
        ToolRequest(tool=ToolName.PATCH_FILE, path=path, old_str="a", new_str="b")
    )
    assert read.decision == PolicyDecisionType.ALLOW
    assert patch.decision == PolicyDecisionType.DENY
    assert patch.policy_id == "PATH-004"


def test_forbidden_wins_over_protected(contract: TaskContract, config: PolicyConfig) -> None:
    engine = PolicyEngine(contract.model_copy(update={"forbidden_paths": ["tests/"]}), config)
    decision = engine.evaluate(ToolRequest(tool=ToolName.READ_FILE, path="tests/test_math.py"))
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_id == "PATH-002"


def test_denies_read_outside_allowed_paths(engine: PolicyEngine) -> None:
    request = ToolRequest(tool=ToolName.READ_FILE, path="README.md")
    decision = engine.evaluate(request)

    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_id == "PATH-003"


def test_denies_forbidden_path_even_though_it_is_inside_an_allowed_path(
    engine: PolicyEngine,
) -> None:
    # contract forbids "src/aigis/policy/" specifically, nested inside the
    # broader "src/" allow -- this is ARCHITECTURE.md section 7's own
    # example ("allow 'src/' but forbid 'src/aigis/policy/policy.yaml'").
    request = ToolRequest(tool=ToolName.READ_FILE, path="src/aigis/policy/policy.yaml")
    decision = engine.evaluate(request)

    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_id == "PATH-002"


@pytest.mark.parametrize(
    "bad_path", ["../etc/passwd", "src/../../etc/passwd", "/etc/passwd", "C:\\Windows\\System32"]
)
def test_denies_path_traversal_and_absolute_paths(engine: PolicyEngine, bad_path: str) -> None:
    request = ToolRequest(tool=ToolName.READ_FILE, path=bad_path)
    decision = engine.evaluate(request)

    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_id == "PATH-001"


def test_denied_decisions_carry_the_original_request_as_evidence(engine: PolicyEngine) -> None:
    request = ToolRequest(tool=ToolName.READ_FILE, path="README.md")
    decision = engine.evaluate(request)

    assert decision.request == request


# --- command rules (RUN_COMMAND) -----------------------------------------------


def test_allows_command_in_allowlist(engine: PolicyEngine) -> None:
    request = ToolRequest(tool=ToolName.RUN_COMMAND, executable="pytest", args=["tests/"])
    decision = engine.evaluate(request)

    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.policy_id == "CMD-000"


def test_denies_command_outside_allowlist(engine: PolicyEngine) -> None:
    request = ToolRequest(tool=ToolName.RUN_COMMAND, executable="rm", args=["-rf", "/"])
    decision = engine.evaluate(request)

    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_id == "CMD-001"
    assert decision.reason == "Executable not in allowlist"


def test_denies_command_with_path_traversal_in_args(engine: PolicyEngine) -> None:
    request = ToolRequest(tool=ToolName.RUN_COMMAND, executable="pytest", args=["../../etc"])
    decision = engine.evaluate(request)

    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_id == "CMD-002"


# --- task risk_level gate (checked before path/command rules) -----------------


def test_critical_risk_denies_everything_regardless_of_request(contract: TaskContract) -> None:
    critical_contract = contract.model_copy(update={"risk_level": RiskLevel.CRITICAL})
    engine = PolicyEngine(critical_contract, PolicyConfig(allowed_commands=["pytest"]))

    request = ToolRequest(tool=ToolName.READ_FILE, path="src/aigis/cli.py")
    decision = engine.evaluate(request)

    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_id == "RISK-001"


def test_high_risk_requires_human_regardless_of_request(contract: TaskContract) -> None:
    high_contract = contract.model_copy(update={"risk_level": RiskLevel.HIGH})
    engine = PolicyEngine(high_contract, PolicyConfig(allowed_commands=["pytest"]))

    request = ToolRequest(tool=ToolName.RUN_COMMAND, executable="pytest", args=[])
    decision = engine.evaluate(request)

    assert decision.decision == PolicyDecisionType.REQUIRE_HUMAN
    assert decision.policy_id == "RISK-002"


def test_low_risk_falls_through_to_normal_path_rules(engine: PolicyEngine) -> None:
    # contract fixture's risk_level is LOW -- confirms the risk gate doesn't
    # swallow LOW/MEDIUM tasks into some other special-cased behavior.
    request = ToolRequest(tool=ToolName.READ_FILE, path="src/aigis/cli.py")
    assert engine.evaluate(request).decision == PolicyDecisionType.ALLOW


# --- default config wiring ------------------------------------------------------


def test_engine_loads_default_policy_config_when_none_given(contract: TaskContract) -> None:
    """P0 D1: the bundled policy has no generic command allowlist, only the
    fixed run_tests/run_lint profiles."""
    engine = PolicyEngine(contract)
    assert engine.config.allowed_commands == []
    assert {profile.id for profile in engine.config.profiles} == {"run_tests", "run_lint"}


# --- fixed profiles (RUN_TESTS / RUN_LINT, P0 D1) -------------------------------


@pytest.mark.parametrize(
    "path", [None, "tests/", "tests/test_math.py::test_add", "src/", "src/aigis/test_x.py"]
)
def test_run_tests_in_allowed_or_protected_scope_is_allowed(
    contract: TaskContract, path: str | None
) -> None:
    decision = PolicyEngine(contract).evaluate(ToolRequest(tool=ToolName.RUN_TESTS, path=path))
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.policy_id == "PROF-000"


@pytest.mark.parametrize(
    ("path", "policy_id"),
    [("../x", "PATH-001"), ("/etc", "PATH-001"), ("docs/", "PATH-003"), ("README.md", "PATH-003")],
)
def test_run_tests_outside_scope_is_denied(
    contract: TaskContract, path: str, policy_id: str
) -> None:
    decision = PolicyEngine(contract).evaluate(ToolRequest(tool=ToolName.RUN_TESTS, path=path))
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_id == policy_id


def test_run_tests_on_a_forbidden_node_id_is_denied() -> None:
    contract = TaskContract(
        task_id="T",
        description="d",
        allowed_paths=["src/"],
        forbidden_paths=["src/secret_tests/"],
        success_criteria=["ok"],
        required_gates=["pytest"],
        max_iterations=1,
        max_runtime_seconds=1,
        max_tool_calls=1,
        max_files_changed=1,
    )
    decision = PolicyEngine(contract).evaluate(
        ToolRequest(tool=ToolName.RUN_TESTS, path="src/secret_tests/test_a.py::test_x")
    )
    assert decision.policy_id == "PATH-002"


def test_run_lint_is_allowed_by_its_profile(contract: TaskContract) -> None:
    decision = PolicyEngine(contract).evaluate(ToolRequest(tool=ToolName.RUN_LINT))
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.policy_id == "PROF-000"


@pytest.mark.parametrize("tool", [ToolName.RUN_TESTS, ToolName.RUN_LINT])
def test_missing_profile_is_denied(contract: TaskContract, tool: ToolName) -> None:
    decision = PolicyEngine(contract, PolicyConfig()).evaluate(ToolRequest(tool=tool))
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_id == "PROF-001"


def test_risk_gate_still_applies_to_profiles(contract: TaskContract) -> None:
    critical = contract.model_copy(update={"risk_level": RiskLevel.CRITICAL})
    decision = PolicyEngine(critical).evaluate(ToolRequest(tool=ToolName.RUN_TESTS))
    assert decision.policy_id == "RISK-001"
