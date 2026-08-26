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
    # contract's allowed_paths are "src/" and "tests/" (directory prefixes);
    # a nested file under either must resolve as within-scope.
    request = ToolRequest(tool=ToolName.READ_FILE, path="tests/test_math.py")
    assert engine.evaluate(request).decision == PolicyDecisionType.ALLOW


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
    engine = PolicyEngine(contract)
    assert "pytest" in engine.config.allowed_commands
