"""Hidden oracle (docs/security/v0.2-design.md, D7) -- host side.

This module only ever runs in the control plane's process. The worker that
executes the agent's code (plan commit 3) receives :func:`worker_inputs`,
never the expected values; the comparison below happens here.

Case shapes (one ``oracle.json`` per task, next to its ``repo/``, never
inside it):

- function: ``module``, ``function``, ``args``, ``kwargs`` and either
  ``expected`` (return value) or ``raises`` (exception class name);
- method: ``module``, ``class``, ``init_args``, ``method``, ``args``,
  ``kwargs`` and ``expected_attrs`` (attributes read after the call) and/or
  ``raises``. With ``raises``, ``expected_attrs`` checks the state did not
  change. The worker only gets the attribute *names* (``state_attrs``).

Optional per case: ``shared_with_visible`` -- the case's input coincides
with a visible test's, with the justification (validity checks require it).

Comparison (Dario, 2026-11-15): int/float numerically with
``math.isclose(rel_tol=1e-9, abs_tol=1e-12)``; bool is distinct from int and
float; str, None, list and dict structurally, applying the same rule to
their elements; exceptions by class name. The oracle must not be stricter
than the specification (``average([]) == 0`` is as good as ``0.0``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

REL_TOL = 1e-9
ABS_TOL = 1e-12

# Keys the worker never receives.
_HIDDEN_KEYS = ("expected", "expected_attrs", "raises", "shared_with_visible")


def values_match(actual: Any, expected: Any) -> bool:
    """The comparison rule above. ``actual`` is what the worker returned,
    already decoded from JSON (tuples arrive as lists)."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is bool and type(expected) is bool and actual == expected
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and math.isclose(
            actual, expected, rel_tol=REL_TOL, abs_tol=ABS_TOL
        )
    if expected is None:
        return actual is None
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(values_match(a, e) for a, e in zip(actual, expected, strict=True))
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(values_match(actual[k], expected[k]) for k in expected)
        )
    return False


def case_passes(case: Mapping[str, Any], outcome: Mapping[str, Any]) -> bool:
    """One case against one worker outcome: ``{"value": v}``,
    ``{"raises": "Name"}`` and/or ``{"attrs": {...}}``."""
    if not isinstance(outcome, Mapping):
        return False
    if "raises" in case:
        if outcome.get("raises") != case["raises"]:
            return False
    elif "raises" in outcome:
        return False
    if "expected_attrs" in case and not values_match(
        outcome.get("attrs"), case["expected_attrs"]
    ):
        return False
    if "expected" in case:
        return "value" in outcome and values_match(outcome["value"], case["expected"])
    return True


def worker_inputs(cases: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """What the worker may see: each case without its expected outcome. A
    method case gets ``state_attrs`` (names only) instead of
    ``expected_attrs``."""
    inputs = []
    for case in cases:
        item = {k: v for k, v in case.items() if k not in _HIDDEN_KEYS}
        if "class" in case:
            item["state_attrs"] = sorted(case.get("expected_attrs", {}))
        inputs.append(item)
    return inputs


__all__ = ["ABS_TOL", "REL_TOL", "case_passes", "values_match", "worker_inputs"]
