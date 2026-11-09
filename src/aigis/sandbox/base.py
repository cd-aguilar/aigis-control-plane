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

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

# Placeholder a caller puts in ``run_command`` args where a report file
# should go (e.g. ``--json-report-file={aigis_report_dir}/r.json``). Each
# sandbox replaces it with the report directory *as the command sees it*:
# the host path for LocalCowSandbox, ``/aigis-report`` (a separate rw
# mount) for DockerSandbox, whose workspace is mounted read-only (P0 D5).
REPORT_DIR_TOKEN = "{aigis_report_dir}"


def expand_report_dir(args: Sequence[str], seen_as: str | None) -> list[str]:
    """Replaces ``REPORT_DIR_TOKEN`` in ``args``. A token with no report
    directory is a caller bug: fail loudly instead of running pytest with a
    literal ``{aigis_report_dir}`` path inside the workspace.
    """
    if seen_as is None:
        if any(REPORT_DIR_TOKEN in arg for arg in args):
            raise ValueError(f"{REPORT_DIR_TOKEN} in args but no report_dir given")
        return list(args)
    return [arg.replace(REPORT_DIR_TOKEN, seen_as) for arg in args]


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

    def create(self, *, exclude: Sequence[str] = ()) -> None:
        """``exclude`` = the contract's ``forbidden_paths`` (P0 D2): those
        paths must not exist in the workspace at all.
        """
        ...

    def read_file(self, path: str) -> str: ...

    def write_file(self, path: str, content: str) -> None: ...

    def run_command(
        self,
        executable: str,
        args: list[str],
        *,
        timeout_seconds: int,
        report_dir: Path | None = None,
    ) -> CommandResult:
        """``report_dir``: a host directory OUTSIDE the workspace, created by
        the caller, where the command may write its report. Referenced in
        ``args`` through ``REPORT_DIR_TOKEN``; the only place a command can
        write besides /tmp in docker mode.
        """
        ...

    def collect_diff(self) -> str: ...

    def changed_paths(self) -> list[str]:
        """Paths that differ from the base repo, observed on the filesystem
        (never from the agent's tool log). Must come from the same
        comparison as ``collect_diff``.
        """
        ...

    def start_evaluation(self, *, protected: Sequence[str]) -> None:
        """Ends the agent phase (P0 D3): replaces the agent's workspace
        with an evaluation workspace built from the BASE repo (minus what
        ``create`` excluded) plus the agent's observed changes outside
        ``protected``. Anything the agent did to a protected path --
        modified, created, deleted, symlinked -- is lost; the gates always
        see the base version. ``run_command`` then runs inside the
        evaluation workspace. ``changed_paths``/``collect_diff`` must be
        read before this call.
        """
        ...

    def destroy(self) -> None: ...
