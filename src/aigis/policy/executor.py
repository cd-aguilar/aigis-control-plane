"""SandboxedToolExecutor — the concrete ``ToolExecutor``
(``agent/executor.py``'s protocol) that Phase 2's ``AgentRuntime`` was built
to accept without modification.

Wires the two Phase 3 pieces together in the only order the project's
thesis allows: PolicyEngine.evaluate() runs first and can short-circuit
before the Sandbox ever sees the request (a DENY/REQUIRE_HUMAN never
touches the filesystem or a subprocess); only an ALLOW reaches the Sandbox.
The result -- whichever branch it came from -- is translated into an
``ExecutionResult`` carrying the ``PolicyDecision`` as part of the evidence,
per ARCHITECTURE.md section 10 ("la autorización [es] parte de la
evidencia").
"""

from __future__ import annotations

from aigis.agent.executor import ExecutionResult
from aigis.domain import (
    ExecutionOutcome,
    PolicyDecision,
    PolicyDecisionType,
    ToolName,
    ToolRequest,
)
from aigis.policy.engine import PolicyEngine
from aigis.sandbox.base import Sandbox


class SandboxedToolExecutor:
    def __init__(
        self, policy_engine: PolicyEngine, sandbox: Sandbox, *, command_timeout_seconds: int = 60
    ) -> None:
        self.policy_engine = policy_engine
        self.sandbox = sandbox
        self.command_timeout_seconds = command_timeout_seconds

    def execute(self, tool_request: ToolRequest) -> ExecutionResult:
        decision = self.policy_engine.evaluate(tool_request)
        if decision.decision != PolicyDecisionType.ALLOW:
            return ExecutionResult(
                outcome=ExecutionOutcome.POLICY_BLOCKED,
                error=f"{decision.decision.value} ({decision.policy_id}): {decision.reason}",
                policy_decision=decision,
            )

        try:
            return self._run_in_sandbox(tool_request, decision)
        except (OSError, ValueError) as exc:
            # A tool-level failure (patch didn't apply, file missing) is
            # evidence, not a crash -- the agent gets a FAILED result back
            # and can try again, same as any other failed attempt.
            return ExecutionResult(
                outcome=ExecutionOutcome.FAILED, error=str(exc), policy_decision=decision
            )

    def _run_in_sandbox(
        self, tool_request: ToolRequest, decision: PolicyDecision
    ) -> ExecutionResult:
        if tool_request.tool is ToolName.READ_FILE:
            content = self.sandbox.read_file(tool_request.path)
            return ExecutionResult(
                outcome=ExecutionOutcome.COMPLETED, output=content, policy_decision=decision
            )

        if tool_request.tool is ToolName.PATCH_FILE:
            changed_path = self._apply_patch(tool_request)
            return ExecutionResult(
                outcome=ExecutionOutcome.COMPLETED,
                output=f"patched {changed_path}",
                policy_decision=decision,
                changed_path=changed_path,
            )

        if tool_request.tool is ToolName.RUN_COMMAND:
            result = self.sandbox.run_command(
                tool_request.executable,
                tool_request.args,
                timeout_seconds=self.command_timeout_seconds,
            )
            if result.timed_out:
                outcome = ExecutionOutcome.TIMEOUT
            elif result.exit_code == 0:
                outcome = ExecutionOutcome.COMPLETED
            else:
                outcome = ExecutionOutcome.FAILED
            return ExecutionResult(
                outcome=outcome,
                output=result.stdout,
                error=None if outcome == ExecutionOutcome.COMPLETED else result.stderr,
                policy_decision=decision,
            )

        raise TypeError(f"unhandled tool: {tool_request.tool!r}")  # pragma: no cover

    def _apply_patch(self, tool_request: ToolRequest) -> str:
        path = tool_request.path
        current = self.sandbox.read_file(path)
        occurrences = current.count(tool_request.old_str)
        if occurrences == 0:
            raise ValueError(f"old_str not found in {path}")
        if occurrences > 1:
            raise ValueError(f"old_str is not unique in {path} ({occurrences} occurrences)")
        updated = current.replace(tool_request.old_str, tool_request.new_str, 1)
        self.sandbox.write_file(path, updated)
        return path


__all__ = ["SandboxedToolExecutor"]
