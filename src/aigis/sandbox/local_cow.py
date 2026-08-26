"""LocalCowSandbox — a copy-on-write-*style* ephemeral workspace using a
plain filesystem copy, plus subprocess execution with whatever isolation the
host OS gives us for free (a fresh temp directory, a stripped environment,
POSIX resource limits where available).

Honest scoping (ARCHITECTURE.md section 3.7/16: "no afirmar seguridad
absoluta"): true copy-on-write needs OverlayFS (Linux-only, typically
root) or a filesystem-level snapshot; this class instead does a full
``shutil.copytree`` into ``tempfile.mkdtemp()``. That's the CoW *pattern*
(base repo untouched, agent writes land in an ephemeral layer, thrown away
on ``destroy()``) without the kernel feature -- portable across the Linux
dev sandbox and Dario's Windows machine, which is what this project actually
runs on. What it does NOT provide: network isolation, a non-root user, or
a read-only base filesystem enforced by the OS -- that's what
``DockerSandbox`` is for when a Docker daemon is available. Both satisfy the
same ``Sandbox`` protocol, so ``policy/executor.py`` doesn't care which one
it's holding.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from aigis.sandbox.base import CommandResult

# Environment variables let through to the sandboxed subprocess. Anything
# not listed here -- API keys, credentials, unrelated host state -- is
# invisible to code running inside the sandbox, per section 16's "secret
# access" mitigation ("ausencia de credenciales sensibles").
_ALLOWED_ENV_VARS = ("PATH", "PYTHONPATH", "SYSTEMROOT", "TEMP", "TMP")


class SandboxPathError(ValueError):
    """A path tried to escape the sandbox workdir. Raised even though the
    Policy Engine should already have denied it (PATH-001) before the
    request ever reached the sandbox -- this is the last line of defense
    if that check is ever bypassed or buggy, not the primary control.
    """


class LocalCowSandbox:
    def __init__(self, base_repo_path: str | Path) -> None:
        self.base_repo_path = Path(base_repo_path).resolve()
        if not self.base_repo_path.is_dir():
            raise NotADirectoryError(f"base_repo_path is not a directory: {self.base_repo_path}")
        self._workdir: Path | None = None

    @property
    def workdir(self) -> Path:
        if self._workdir is None:
            raise RuntimeError("sandbox not created yet -- call create() first")
        return self._workdir

    def create(self) -> None:
        if self._workdir is not None:
            raise RuntimeError("sandbox already created")
        tmp = Path(tempfile.mkdtemp(prefix="aigis-sandbox-"))
        # copytree requires the destination not to already exist.
        workdir = tmp / "workspace"
        shutil.copytree(self.base_repo_path, workdir)
        self._workdir = workdir

    def _resolve(self, path: str) -> Path:
        candidate = (self.workdir / path).resolve()
        try:
            candidate.relative_to(self.workdir.resolve())
        except ValueError as exc:
            raise SandboxPathError(f"path escapes sandbox workdir: {path!r}") from exc
        return candidate

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise FileNotFoundError(f"no such file in sandbox: {path}")
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def run_command(
        self, executable: str, args: list[str], *, timeout_seconds: int
    ) -> CommandResult:
        env = {name: os.environ[name] for name in _ALLOWED_ENV_VARS if name in os.environ}
        try:
            completed = subprocess.run(  # noqa: S603 -- argv list, never shell=True
                [executable, *args],
                cwd=self.workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                preexec_fn=_apply_resource_limits if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                exit_code=-1,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "")
                + f"\n[aigis] command exceeded {timeout_seconds}s timeout",
                timed_out=True,
            )
        except FileNotFoundError:
            return CommandResult(
                exit_code=127, stdout="", stderr=f"executable not found: {executable}"
            )
        return CommandResult(
            exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )

    def collect_diff(self) -> str:
        return _unified_diff_tree(self.base_repo_path, self.workdir)

    def destroy(self) -> None:
        if self._workdir is not None:
            shutil.rmtree(self._workdir.parent, ignore_errors=True)
            self._workdir = None


def _apply_resource_limits() -> None:
    """``preexec_fn`` for POSIX: caps CPU time, address space and process
    count for the sandboxed subprocess (ARCHITECTURE.md section 16,
    "resource exhaustion" -> "CPU/memory/PID/time limits"). Runs in the
    forked child before exec, so a limit here can never affect the parent.
    Not available on Windows -- ``run_command`` only wires this in when
    ``os.name == "posix"``.
    """
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (1 * 1024 * 1024 * 1024, 1 * 1024 * 1024 * 1024))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except (ValueError, OSError):  # pragma: no cover -- not all platforms allow this
        pass


# Directories/suffixes that are execution byproducts, not agent-authored
# changes -- excluded from the diff so e.g. a __pycache__/*.pyc created by
# run_command('python', ...) doesn't show up as a "changed file", and so a
# binary .pyc never reaches the UTF-8 decode below.
_DIFF_IGNORED_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}
_DIFF_IGNORED_SUFFIXES = {".pyc", ".pyo"}


def _is_diff_ignored(path: Path, root: Path) -> bool:
    if path.suffix in _DIFF_IGNORED_SUFFIXES:
        return True
    return any(part in _DIFF_IGNORED_DIR_NAMES for part in path.relative_to(root).parts)


def _read_text_or_none(path: Path) -> str | None:
    """None means "binary, or otherwise not diffable as text" -- distinct
    from "" (an empty file), which is a normal diffable case.
    """
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _unified_diff_tree(base: Path, workdir: Path) -> str:
    """Unified diff of every file that differs between ``base`` and
    ``workdir``, concatenated into one patch string -- the plain-filesystem
    equivalent of ``git diff`` for a base repo that may not itself be a git
    repository (the toy repos this sandbox runs against, per CLAUDE.md's
    "repo de juguete local").
    """
    base_files = {
        p.relative_to(base).as_posix()
        for p in base.rglob("*")
        if p.is_file() and not _is_diff_ignored(p, base)
    }
    work_files = {
        p.relative_to(workdir).as_posix()
        for p in workdir.rglob("*")
        if p.is_file() and not _is_diff_ignored(p, workdir)
    }

    chunks: list[str] = []
    for rel_path in sorted(base_files | work_files):
        base_text = _read_text_or_none(base / rel_path)
        work_text = _read_text_or_none(workdir / rel_path)

        if base_text is None or work_text is None:
            base_bytes = (base / rel_path).read_bytes() if (base / rel_path).is_file() else None
            work_bytes = (
                (workdir / rel_path).read_bytes() if (workdir / rel_path).is_file() else None
            )
            if base_bytes != work_bytes:
                chunks.append(f"Binary files a/{rel_path} and b/{rel_path} differ")
            continue

        base_lines = base_text.splitlines(keepends=True)
        work_lines = work_text.splitlines(keepends=True)
        if base_lines == work_lines:
            continue
        diff = difflib.unified_diff(
            base_lines, work_lines, fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}"
        )
        chunks.append("".join(diff))
    return "\n".join(chunks)


__all__ = ["LocalCowSandbox", "SandboxPathError"]
