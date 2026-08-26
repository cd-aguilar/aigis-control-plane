"""Policy Engine: deterministic ALLOW/DENY/REQUIRE_HUMAN authorization.

Per ARCHITECTURE.md section 10. See ``engine.py`` for the rules and
``executor.py`` for the concrete ``ToolExecutor`` that wires this in front
of a Sandbox.
"""

from aigis.policy.config import DEFAULT_POLICY_PATH, PolicyConfig, load_policy_config
from aigis.policy.engine import PolicyEngine
from aigis.policy.executor import SandboxedToolExecutor

__all__ = [
    "DEFAULT_POLICY_PATH",
    "PolicyConfig",
    "load_policy_config",
    "PolicyEngine",
    "SandboxedToolExecutor",
]
