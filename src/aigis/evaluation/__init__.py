"""Quality Gates + Decision Engine + Security Evaluation Suite: turns a
run's evidence into a verdict.

Per ARCHITECTURE.md section 12 (Quality Gates), section 15 (Modelo de
resultados) and section 17 (Security Evaluation Suite). See ``gates.py`` for
the deterministic pytest/ruff gates that run inside a Sandbox,
``decision_engine.py`` for the PASS/FAIL/NEEDS_HUMAN verdict computed from
their results plus policy/scope/limit checks -- never from what the agent
claims -- and ``security_suite.py`` for S01/S02, which grade the Policy
Engine's containment the same way (a ``GateResult`` with ``GateType.SECURITY``).
"""

from aigis.evaluation.decision_engine import DecisionEngine
from aigis.evaluation.gates import PytestGate, QualityGate, RuffGate
from aigis.evaluation.security_suite import (
    SCENARIOS,
    ScriptedProvider,
    SecurityScenario,
    prompt_injection_scenario,
    run_scenario,
    secret_access_scenario,
)

__all__ = [
    "DecisionEngine",
    "PytestGate",
    "QualityGate",
    "RuffGate",
    "SCENARIOS",
    "ScriptedProvider",
    "SecurityScenario",
    "prompt_injection_scenario",
    "run_scenario",
    "secret_access_scenario",
]
