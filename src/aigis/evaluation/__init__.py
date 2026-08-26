"""Quality Gates + Decision Engine: turns a run's evidence into a verdict.

Per ARCHITECTURE.md section 12 (Quality Gates) and section 15 (Modelo de
resultados). See ``gates.py`` for the deterministic pytest/ruff gates that
run inside a Sandbox, and ``decision_engine.py`` for the PASS/FAIL/
NEEDS_HUMAN verdict computed from their results plus policy/scope/limit
checks -- never from what the agent claims.
"""

from aigis.evaluation.decision_engine import DecisionEngine
from aigis.evaluation.gates import PytestGate, QualityGate, RuffGate

__all__ = [
    "DecisionEngine",
    "PytestGate",
    "QualityGate",
    "RuffGate",
]
