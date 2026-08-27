"""Quality Gates + Decision Engine + Security Evaluation Suite + functional
benchmark tasks: turns a run's evidence into a verdict, and provides the
task fixtures used to measure the agent under it.

Per ARCHITECTURE.md section 12 (Quality Gates), section 15 (Modelo de
resultados), section 17 (Security Evaluation Suite) and section 18
(Evaluation Suite funcional). See ``gates.py`` for the deterministic
pytest/ruff gates that run inside a Sandbox, ``decision_engine.py`` for the
PASS/FAIL/NEEDS_HUMAN verdict computed from their results plus
policy/scope/limit checks -- never from what the agent claims --
``security_suite.py`` for S01/S02, which grade the Policy Engine's
containment the same way (a ``GateResult`` with ``GateType.SECURITY``), and
``benchmark_tasks.py`` for T01-T08, meant to run against a real
``Provider`` via ``orchestrator.run_task``.
"""

from aigis.evaluation.benchmark_tasks import (
    TASKS,
    BenchmarkTask,
    add_validation_with_decoy_task,
    configuration_change_task,
    fix_documented_contract_task,
    fix_edge_case_task,
    fix_failing_test_task,
    fix_regression_task,
    implement_missing_function_task,
    refactor_duplicated_bug_task,
)
from aigis.evaluation.benchmark_tasks import materialize as materialize_benchmark_task
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
    "TASKS",
    "BenchmarkTask",
    "add_validation_with_decoy_task",
    "configuration_change_task",
    "fix_documented_contract_task",
    "fix_edge_case_task",
    "fix_failing_test_task",
    "fix_regression_task",
    "implement_missing_function_task",
    "refactor_duplicated_bug_task",
    "materialize_benchmark_task",
]
