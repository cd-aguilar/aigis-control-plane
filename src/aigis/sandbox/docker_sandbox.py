"""DockerSandbox — the isolated Sandbox from ARCHITECTURE.md section 11.

Reuses ``LocalCowSandbox`` for everything filesystem-shaped (``create``,
``read_file``, ``write_file``, ``collect_diff``, ``start_evaluation``,
``destroy`` all operate on the same host-side ephemeral copy) and overrides
only ``run_command`` to execute inside a one-shot container (``docker run
--rm``) instead of a bare host subprocess.

Hardening (P0 D5):

- The image is the AIGIS sandbox image (``sandbox/Dockerfile``: base pinned
  by digest, pytest / pytest-json-report / ruff pinned to the ``dev``
  extra, non-root user). A local build is not reproducible byte for byte,
  so the reference is the built *image ID*: ``make sandbox-image`` records
  it in ``sandbox/.image-id`` (or set ``AIGIS_SANDBOX_IMAGE_ID``, or pass
  ``expected_image_id``). Before the first command the tag must resolve to
  exactly that ID -- otherwise ``SandboxImageError`` -- and every command
  then runs the image *by ID*, so a retag between the check and the run
  changes nothing.
- Flags: ``--network none``, ``--cap-drop ALL``, ``--security-opt
  no-new-privileges``, ``--read-only`` root with a ``--tmpfs /tmp``,
  ``--pids-limit``/``--memory``/``--cpus``, non-root ``--user``.
- Mounts: the workspace is mounted **read-only** in every run. Every write
  the agent makes goes through ``patch_file`` on the host side, so nothing
  executed in the container needs to write there (pytest runs with
  ``-p no:cacheprovider`` and ``PYTHONDONTWRITEBYTECODE=1``, ruff with
  ``--no-cache``). A command's report goes to a second, rw mount,
  ``/aigis-report``: a host directory the caller creates outside the
  workspace (``report_dir``). The base repo is never mounted.
- User: the host's ``uid:gid`` when the host is POSIX and not root (the
  workspace is the host user's, often mode 0700); ``1000:1000`` otherwise
  (root host, or no uid at all -- Windows / Docker Desktop, whose bind
  mounts are readable regardless of uid).

Shells out to the ``docker`` CLI rather than depending on the Docker SDK:
the base install shouldn't need Docker just to import this module.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

from aigis.sandbox.base import CommandResult, expand_report_dir
from aigis.sandbox.local_cow import LocalCowSandbox

DEFAULT_IMAGE = "aigis-sandbox:local"
CONTAINER_WORKDIR = "/workspace"
CONTAINER_REPORT_DIR = "/aigis-report"
IMAGE_ID_ENV = "AIGIS_SANDBOX_IMAGE_ID"
# src/aigis/sandbox/docker_sandbox.py -> repo root / sandbox / .image-id
IMAGE_ID_FILE = Path(__file__).resolve().parents[3] / "sandbox" / ".image-id"
_FALLBACK_USER = "1000:1000"


class SandboxImageError(RuntimeError):
    """The sandbox image is missing, or is not the one recorded at build
    time. No command runs; ``run_task`` turns this into NEEDS_HUMAN."""


def container_user() -> str:
    """``uid:gid`` for ``--user``: the host user's on a non-root POSIX host,
    ``1000:1000`` on a root host or where there is no uid (Windows)."""
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return _FALLBACK_USER
    uid = getuid()
    if uid == 0:
        return _FALLBACK_USER
    return f"{uid}:{getgid()}"


def build_docker_run_argv(
    *,
    image: str,
    workdir_host_path: str,
    executable: str,
    args: list[str],
    report_dir_host_path: str | None = None,
    user: str = _FALLBACK_USER,
    name: str | None = None,
    memory: str = "512m",
    cpus: str = "1",
    pids_limit: int = 128,
) -> list[str]:
    """Pure argv construction, so every security-relevant flag can be
    asserted on without a Docker daemon (tests/sandbox/test_docker_sandbox.py).
    ``args`` must already be expanded (``REPORT_DIR_TOKEN`` ->
    ``/aigis-report``).
    """
    argv = ["docker", "run", "--rm"]
    if name is not None:
        argv += ["--name", name]
    argv += [
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        user,
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--memory",
        memory,
        "--cpus",
        cpus,
        "--pids-limit",
        str(pids_limit),
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "HOME=/tmp",
        "-v",
        f"{workdir_host_path}:{CONTAINER_WORKDIR}:ro",
    ]
    if report_dir_host_path is not None:
        argv += ["-v", f"{report_dir_host_path}:{CONTAINER_REPORT_DIR}:rw"]
    argv += ["-w", CONTAINER_WORKDIR, image, executable, *args]
    return argv


def _docker(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603, S607 -- argv list, never shell=True
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )


class DockerSandbox(LocalCowSandbox):
    def __init__(
        self,
        base_repo_path: str | Path,
        *,
        image: str = DEFAULT_IMAGE,
        expected_image_id: str | None = None,
    ) -> None:
        super().__init__(base_repo_path)
        self.image = image
        self._expected_image_id = expected_image_id
        self.image_id: str | None = None  # set by verify_image()

    @staticmethod
    def is_available() -> bool:
        """False if the ``docker`` binary is missing or no daemon answers."""
        if shutil.which("docker") is None:
            return False
        try:
            result = _docker(["version", "--format", "{{.Server.Version}}"], timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def expected_image_id(self) -> str:
        """The image ID recorded at build time: explicit argument, then
        ``AIGIS_SANDBOX_IMAGE_ID``, then ``sandbox/.image-id``."""
        candidates = (
            self._expected_image_id,
            os.environ.get(IMAGE_ID_ENV),
            IMAGE_ID_FILE.read_text(encoding="utf-8") if IMAGE_ID_FILE.is_file() else None,
        )
        for candidate in candidates:
            if candidate and candidate.strip():
                return candidate.strip()
        raise SandboxImageError(
            f"no expected sandbox image ID: run `make sandbox-image` (writes {IMAGE_ID_FILE}) "
            f"or set {IMAGE_ID_ENV}"
        )

    def verify_image(self) -> str:
        """Checks that ``self.image`` resolves to the expected image ID and
        pins it. Idempotent. Raises ``SandboxImageError`` otherwise."""
        if self.image_id is not None:
            return self.image_id
        if not self.is_available():
            raise SandboxImageError("Docker daemon not available: cannot verify the sandbox image")
        expected = self.expected_image_id()
        try:
            inspected = _docker(["image", "inspect", "--format", "{{.Id}}", self.image])
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxImageError(f"cannot inspect sandbox image {self.image}: {exc}") from exc
        if inspected.returncode != 0:
            raise SandboxImageError(
                f"sandbox image {self.image} not found: run `make sandbox-image`"
            )
        actual = inspected.stdout.strip()
        if actual != expected:
            raise SandboxImageError(
                f"sandbox image {self.image} is {actual}, expected {expected}: "
                "rebuild it with `make sandbox-image` or fix the recorded ID"
            )
        self.image_id = actual
        return actual

    def run_command(
        self,
        executable: str,
        args: list[str],
        *,
        timeout_seconds: int,
        report_dir: Path | None = None,
    ) -> CommandResult:
        if not self.is_available():
            raise RuntimeError(
                "DockerSandbox.run_command requires a reachable Docker daemon; "
                "start Docker (or run with --unsafe-local)"
            )
        image_id = self.verify_image()
        user = container_user()
        if user == _FALLBACK_USER and os.name == "posix":
            # Root host: the container's uid 1000 must still read the
            # workspace and write the report directory.
            os.chmod(self.workdir, 0o755)
            if report_dir is not None:
                os.chmod(report_dir, 0o777)
        name = f"aigis-{uuid.uuid4().hex[:12]}"
        argv = build_docker_run_argv(
            image=image_id,
            workdir_host_path=str(self.workdir),
            executable=executable,
            args=expand_report_dir(args, CONTAINER_REPORT_DIR if report_dir is not None else None),
            report_dir_host_path=str(report_dir) if report_dir is not None else None,
            user=user,
            name=name,
        )
        try:
            completed = subprocess.run(  # noqa: S603
                argv, capture_output=True, text=True, timeout=timeout_seconds
            )
        except subprocess.TimeoutExpired as exc:
            # Killing the docker CLI does not stop the container: kill it.
            try:
                _docker(["kill", name], timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return CommandResult(
                exit_code=-1,
                stdout=_text(exc.stdout),
                stderr=_text(exc.stderr) + f"\n[aigis] command exceeded {timeout_seconds}s timeout",
                timed_out=True,
            )
        return CommandResult(
            exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


__all__ = [
    "CONTAINER_REPORT_DIR",
    "CONTAINER_WORKDIR",
    "DEFAULT_IMAGE",
    "IMAGE_ID_ENV",
    "IMAGE_ID_FILE",
    "DockerSandbox",
    "SandboxImageError",
    "build_docker_run_argv",
    "container_user",
]
