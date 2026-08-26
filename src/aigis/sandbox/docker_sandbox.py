"""DockerSandbox — the "real" Sandbox from ARCHITECTURE.md section 11:
Docker, non-root, network disabled, resource limits, read-only base
repository, ephemeral filesystem.

Reuses ``LocalCowSandbox`` for everything filesystem-shaped (``create``,
``read_file``, ``write_file``, ``collect_diff``, ``destroy`` all operate on
the same host-side ephemeral copy) and overrides only ``run_command`` to
execute inside an isolated, one-shot container instead of a bare host
subprocess. That copy is bind-mounted into the container per invocation
(``docker run --rm ...``, no long-lived container to manage or clean up
between commands) -- deliberately not a persistent container, to keep the
security surface (and the code) as small as the "one command per
ToolRequest" shape the rest of the system already assumes.

Shells out to the ``docker`` CLI via ``subprocess`` rather than depending on
the ``docker`` Python SDK, for the same reason ``providers/claude.py``
lazy-imports ``anthropic``: the base install shouldn't need Docker just to
import this module, only to actually use it. ``is_available()`` lets a
caller check before relying on it, the same shape as
``ClaudeProvider.__init__``'s "clear error, not a confusing one" pattern
for a missing ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import shutil
import subprocess

from aigis.sandbox.base import CommandResult
from aigis.sandbox.local_cow import LocalCowSandbox

DEFAULT_IMAGE = "python:3.11-slim"


def build_docker_run_argv(
    *,
    image: str,
    workdir_host_path: str,
    executable: str,
    args: list[str],
    memory: str = "512m",
    cpus: str = "1",
    pids_limit: int = 128,
) -> list[str]:
    """Pure argv construction, factored out so the security-relevant flags
    (no network, non-root, read-only, resource caps) can be asserted on in a
    unit test without a real Docker daemon -- see tests/sandbox/
    test_docker_sandbox.py.

    Every flag here maps directly to a row in ARCHITECTURE.md section 16's
    threat table: --network none (network exfiltration), --user (unauthorized
    privilege), --read-only + one --tmpfs (ephemeral filesystem, read-only
    base), --memory/--cpus/--pids-limit (resource exhaustion).
    """
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "1000:1000",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--memory",
        memory,
        "--cpus",
        cpus,
        "--pids-limit",
        str(pids_limit),
        "-v",
        f"{workdir_host_path}:/workspace:rw",
        "-w",
        "/workspace",
        image,
        executable,
        *args,
    ]


class DockerSandbox(LocalCowSandbox):
    def __init__(self, base_repo_path: str, *, image: str = DEFAULT_IMAGE) -> None:
        super().__init__(base_repo_path)
        self.image = image

    @staticmethod
    def is_available() -> bool:
        """False if the ``docker`` binary is missing or no daemon answers --
        callers should check this (or catch the RuntimeError ``run_command``
        raises) rather than assume Docker is present, since neither the dev
        sandbox nor every deployment target necessarily has it.
        """
        if shutil.which("docker") is None:
            return False
        try:
            result = subprocess.run(  # noqa: S603, S607
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def run_command(
        self, executable: str, args: list[str], *, timeout_seconds: int
    ) -> CommandResult:
        if not self.is_available():
            raise RuntimeError(
                "DockerSandbox.run_command requires a reachable Docker daemon; "
                "use LocalCowSandbox instead, or start Docker"
            )
        argv = build_docker_run_argv(
            image=self.image,
            workdir_host_path=str(self.workdir),
            executable=executable,
            args=args,
        )
        try:
            completed = subprocess.run(  # noqa: S603
                argv, capture_output=True, text=True, timeout=timeout_seconds
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                exit_code=-1,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "")
                + f"\n[aigis] command exceeded {timeout_seconds}s timeout",
                timed_out=True,
            )
        return CommandResult(
            exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )


__all__ = ["DEFAULT_IMAGE", "DockerSandbox", "build_docker_run_argv"]
