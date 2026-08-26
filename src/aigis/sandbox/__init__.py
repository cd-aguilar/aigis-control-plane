"""Sandbox: isolated execution for an ALLOWed ToolRequest.

Per ARCHITECTURE.md section 11. See ``base.py`` for the ``Sandbox``
protocol both implementations satisfy.
"""

from aigis.sandbox.base import CommandResult, Sandbox
from aigis.sandbox.docker_sandbox import DEFAULT_IMAGE, DockerSandbox, build_docker_run_argv
from aigis.sandbox.local_cow import LocalCowSandbox, SandboxPathError

__all__ = [
    "CommandResult",
    "Sandbox",
    "DEFAULT_IMAGE",
    "DockerSandbox",
    "build_docker_run_argv",
    "LocalCowSandbox",
    "SandboxPathError",
]
