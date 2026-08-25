from __future__ import annotations

from aigis.agent.executor import ExecutionResult
from aigis.agent.provider import ProviderAction
from aigis.domain import ExecutionOutcome, TaskContract, TaskState, ToolRequest


class FakeProvider:
    """Test double for Provider: returns pre-programmed actions in order,
    and records every (contract, state) it was called with so tests can
    assert whether/how many times it was consulted.
    """

    def __init__(self, actions: list[ProviderAction]) -> None:
        self._actions = list(actions)
        self.calls: list[tuple[TaskContract, TaskState]] = []

    def propose_action(self, contract: TaskContract, state: TaskState) -> ProviderAction:
        self.calls.append((contract, state))
        if not self._actions:
            raise AssertionError("FakeProvider ran out of programmed actions")
        return self._actions.pop(0)


class FakeExecutor:
    """Test double for ToolExecutor: returns pre-programmed results in
    order (defaulting to a plain COMPLETED result if none were queued), and
    records every ToolRequest it was asked to execute.
    """

    def __init__(self, results: list[ExecutionResult] | None = None) -> None:
        self._results = list(results) if results is not None else None
        self.calls: list[ToolRequest] = []

    def execute(self, tool_request: ToolRequest) -> ExecutionResult:
        self.calls.append(tool_request)
        if self._results is not None:
            if not self._results:
                raise AssertionError("FakeExecutor ran out of programmed results")
            return self._results.pop(0)
        return ExecutionResult(outcome=ExecutionOutcome.COMPLETED, output="ok")
