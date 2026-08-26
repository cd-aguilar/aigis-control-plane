"""DecisionEngine — computes the one output that matters, from evidence.

Per the project's central thesis: "The agent can claim it is done. The
system decides whether it is true." This module never reads
``TaskState.agent_claims`` — only ``Attempt``/``PolicyDecision`` records
(what actually happened) and ``GateResult``s (what the Quality Gates
measured).

Rule order, fail-closed (ARCHITECTURE.md section 3.6, "cuando no hay certeza
suficiente, DENY o NEEDS_HUMAN — nunca se concede autoridad implícita"):

1. Any ``PolicyDecision`` in the run's attempts came back REQUIRE_HUMAN (task
   ``risk_level`` HIGH, per ``policy/engine.py``) → ``NEEDS_HUMAN``,
   regardless of how every other check turned out. A DENY, by contrast, does
   *not* trigger this — per section 15's example, an agent being correctly
   blocked and then completing the task legitimately is still a PASS.
2. A required gate has no result at all (couldn't run, crashed before
   producing a report) → ``NEEDS_HUMAN``. This is genuinely different from a
   gate that ran and failed: the Decision Engine has no verdict to trust
   either way, so it asks a human rather than guessing PASS or FAIL.
3. Otherwise, if any of the six booleans in the Decision formula
   (``contract_valid AND policy_ok AND tests_pass AND lint_pass AND
   scope_ok AND resource_limits_ok``) is False → ``FAIL``. This is a
   deterministic, explainable failure — no ambiguity to escalate to a human.
4. All six True → ``PASS``.
"""

from __future__ import annotations

from aigis.domain import Decision, GateResult, PolicyDecisionType, TaskContract, TaskState
from aigis.domain.enums import FinalDecision, GateType
from aigis.policy.engine import path_within_scope


class DecisionEngine:
    def decide(
        self,
        *,
        run_id: str,
        contract: TaskContract,
        state: TaskState,
        gate_results: list[GateResult],
    ) -> Decision:
        policy_ok = not any(
            attempt.policy_decision is not None
            and attempt.policy_decision.decision == PolicyDecisionType.REQUIRE_HUMAN
            for attempt in state.attempts
        )
        scope_ok = all(
            path_within_scope(path, contract) for path in state.files_changed
        )
        resource_limits_ok = state.is_within_limits(contract)

        by_name = {gate.gate_name: gate for gate in gate_results}
        missing_gates = [name for name in contract.required_gates if name not in by_name]

        # A missing gate can't be attributed to TEST or LINT without knowing
        # its type in advance, so it forces BOTH booleans False rather than
        # neither -- otherwise a missing required gate whose type happens not
        # to be checked here could leave tests_pass/lint_pass vacuously True,
        # which would make Decision's own validator reject the NEEDS_HUMAN
        # this method returns below (all_gates_ok True implies final MUST be
        # PASS). Any missing required gate has to cost at least one boolean.
        gates_present = not missing_gates
        tests_pass = gates_present and self._all_of_type_pass(contract, by_name, GateType.TEST)
        lint_pass = gates_present and self._all_of_type_pass(contract, by_name, GateType.LINT)

        # contract_valid: a TaskContract that exists as this typed object has
        # already survived every Pydantic validator (paths not blank,
        # allowed/forbidden don't overlap, etc.) — there is no further
        # runtime check to perform here, this field just makes the formula's
        # six terms explicit and available for the Decision model's own
        # cross-field invariant.
        contract_valid = True

        if not policy_ok:
            return self._build(
                run_id,
                contract,
                contract_valid,
                policy_ok,
                tests_pass,
                lint_pass,
                scope_ok,
                resource_limits_ok,
                final=FinalDecision.NEEDS_HUMAN,
                reason="task risk_level required human approval (REQUIRE_HUMAN policy decision)",
            )

        if missing_gates:
            return self._build(
                run_id,
                contract,
                contract_valid,
                policy_ok,
                tests_pass,
                lint_pass,
                scope_ok,
                resource_limits_ok,
                final=FinalDecision.NEEDS_HUMAN,
                reason=f"required gate(s) produced no result, cannot verify: {missing_gates}",
            )

        all_ok = (
            contract_valid
            and policy_ok
            and tests_pass
            and lint_pass
            and scope_ok
            and resource_limits_ok
        )
        if not all_ok:
            failed = [
                name
                for name, value in (
                    ("contract_valid", contract_valid),
                    ("policy_ok", policy_ok),
                    ("tests_pass", tests_pass),
                    ("lint_pass", lint_pass),
                    ("scope_ok", scope_ok),
                    ("resource_limits_ok", resource_limits_ok),
                )
                if not value
            ]
            return self._build(
                run_id,
                contract,
                contract_valid,
                policy_ok,
                tests_pass,
                lint_pass,
                scope_ok,
                resource_limits_ok,
                final=FinalDecision.FAIL,
                reason=f"failed check(s): {failed}",
            )

        return self._build(
            run_id,
            contract,
            contract_valid,
            policy_ok,
            tests_pass,
            lint_pass,
            scope_ok,
            resource_limits_ok,
            final=FinalDecision.PASS,
            reason="policy satisfied, all required gates passed, in scope and within limits",
        )

    @staticmethod
    def _all_of_type_pass(
        contract: TaskContract, by_name: dict[str, GateResult], gate_type: GateType
    ) -> bool:
        """True unless a required gate of this type ran and failed. Only
        called once the caller has confirmed every required gate produced a
        result — a missing gate is handled upstream (NEEDS_HUMAN), not here.
        """
        relevant = [
            by_name[name]
            for name in contract.required_gates
            if by_name[name].gate_type == gate_type
        ]
        return all(gate.passed for gate in relevant)

    @staticmethod
    def _build(
        run_id: str,
        contract: TaskContract,
        contract_valid: bool,
        policy_ok: bool,
        tests_pass: bool,
        lint_pass: bool,
        scope_ok: bool,
        resource_limits_ok: bool,
        *,
        final: FinalDecision,
        reason: str,
    ) -> Decision:
        return Decision(
            run_id=run_id,
            task_id=contract.task_id,
            contract_valid=contract_valid,
            policy_ok=policy_ok,
            tests_pass=tests_pass,
            lint_pass=lint_pass,
            scope_ok=scope_ok,
            resource_limits_ok=resource_limits_ok,
            final=final,
            reason=reason,
            evidence_ref=f"evidence/{run_id}/",
        )


__all__ = ["DecisionEngine"]
