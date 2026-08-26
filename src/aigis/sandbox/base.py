"""Sandbox — the isolation boundary an ALLOWed ToolRequest actually runs
inside of.

Per ARCHITECTURE.md section 11, the abstraction is deliberately narrow:

    class Sandbox:
        create()
        execute()
        collect_diff()
        destroy()

adapted here to the tool-request granularity the rest of the system already
works in (``read_file`` / ``write_file`` for READ_FILE/PATCH_FILE,
``run_command`` for RUN_COMMAND) so ``policy/executor.py`` can drive it
directly. Swapping the implementation (local ephemeral copy vs. Docker,
``docker_sandbox.py``) never requires changing ``policy/executor.py`` or
anything upstream of it -- same dependency-inversion shape as
``agent/executor.py``'s ToolExecutor protocol in Phase 2.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class CommandResult(BaseModel):
    """What came back from running one command inside the sandbox.

    Not domain evidence itself (that's ``Attempt``/``ExecutionResult``,
    assembled by ``policy/executor.py`` from this) -- this is the sandbox
    layer's own return type, kept separate so ``sandbox/`` has no
    dependency on ``agent/`` or ``domain/`` result shapes.
    """

    model_config = {"frozen": True}

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class Sandbox(Protocol):
    """Lifecycle: ``create()`` once, any number of ``read_file`` /
    ``write_file`` / ``run_command`` calls, then always ``destroy()`` -- even
    on an exception, callers should ``try/finally`` this (see
    ``policy/executor.py``).
    """

    def create(self) -> None: ...

    def read_file(self, path: str) -> str: ...

    def write_file(self, path: str, content: str) -> None: ...

    def run_command(
        self, executable: str, args: list[str], *, timeout_seconds: int
    ) -> CommandResult: ...

    def collect_diff(self) -> str: ...

    def destroy(self) -> None: ...
