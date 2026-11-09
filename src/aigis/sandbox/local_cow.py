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
import stat
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from aigis.domain.task_contract import path_matches_protected
from aigis.policy.engine import path_matches_prefix
from aigis.sandbox.base import CommandResult, expand_report_dir

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
    # Recorded in environment.json (P0 D5): commands run as host
    # subprocesses, with the host filesystem and the network visible.
    isolation = "none"

    def __init__(self, base_repo_path: str | Path) -> None:
        self.base_repo_path = Path(base_repo_path).resolve()
        if not self.base_repo_path.is_dir():
            raise NotADirectoryError(f"base_repo_path is not a directory: {self.base_repo_path}")
        self._workdir: Path | None = None
        # Paths of the base repo that create() deliberately did NOT copy
        # (P0 D2), with the reason -- reported in the Evidence Bundle.
        self.excluded_paths: list[dict[str, str]] = []
        self._exclude: tuple[str, ...] = ()
        # P0 D3: set by start_evaluation(). Agent changes that did NOT make
        # it into the evaluation workspace, with the reason.
        self.evaluating = False
        self.discarded_changes: list[dict[str, str]] = []

    @property
    def workdir(self) -> Path:
        if self._workdir is None:
            raise RuntimeError("sandbox not created yet -- call create() first")
        return self._workdir

    def create(self, *, exclude: Sequence[str] = ()) -> None:
        """Copy the base repo into a fresh workspace, minus ``exclude``
        (the contract's ``forbidden_paths``, P0 D2): a forbidden file is not
        filtered at read time, it is simply absent -- no executed code can
        read what is not there.

        ``exclude`` uses the same prefix rule as the Policy Engine
        (``path_matches_prefix``): ``"config/"`` drops the whole subtree.
        Symlinks are copied as symlinks (never followed), and a symlink in
        the base is itself excluded when it is absolute, resolves outside
        the repo, or resolves into an excluded path -- otherwise a link
        could re-expose a forbidden file or a host file. Every exclusion is
        recorded in ``excluded_paths``.
        """
        if self._workdir is not None:
            raise RuntimeError("sandbox already created")
        self._exclude = tuple(exclude)
        self.excluded_paths = []
        tmp = Path(tempfile.mkdtemp(prefix="aigis-sandbox-"))
        # copytree requires the destination not to already exist.
        workdir = tmp / "workspace"
        # symlinks=True: a symlink in the base repo stays a symlink. The
        # default (False) would copy the *target's* content -- possibly a
        # host file outside the repo -- into the workspace, and the observed
        # change set (changed_paths) would then see a spurious type change.
        shutil.copytree(
            self.base_repo_path, workdir, symlinks=True, ignore=self._copy_ignore
        )
        self._workdir = workdir

    def _is_forbidden(self, rel_path: str) -> bool:
        return any(path_matches_prefix(rel_path, prefix) for prefix in self._exclude)

    def _unsafe_link_reason(self, link: Path) -> str | None:
        target = os.readlink(link)
        if os.path.isabs(target) or PureWindowsPath(target).drive:
            return "symlink_absolute"
        resolved = Path(os.path.realpath(link))
        try:
            rel_target = resolved.relative_to(self.base_repo_path).as_posix()
        except ValueError:
            return "symlink_outside_repo"
        if self._is_forbidden(rel_target):
            return "symlink_to_forbidden"
        return None

    def _copy_ignore(self, dirpath: str, names: list[str]) -> list[str]:
        rel_dir = Path(dirpath).resolve().relative_to(self.base_repo_path)
        skipped: list[str] = []
        for name in names:
            rel_path = (rel_dir / name).as_posix()
            full = Path(dirpath) / name
            if self._is_forbidden(rel_path):
                reason = "forbidden_path"
            elif full.is_symlink():
                reason = self._unsafe_link_reason(full)
            else:
                reason = None
            if reason is not None:
                skipped.append(name)
                self.excluded_paths.append({"path": rel_path, "reason": reason})
        return skipped

    def _excluded_from_base(self, rel_path: str) -> bool:
        """Same set create() skipped -- so a path that was never copied is
        not reported as a deletion by changed_paths()/collect_diff().
        Applied to the BASE side only: anything the agent creates in the
        workspace, forbidden or not, is always visible as a change.
        """
        return any(
            path_matches_prefix(rel_path, entry["path"]) for entry in self.excluded_paths
        )

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
        self,
        executable: str,
        args: list[str],
        *,
        timeout_seconds: int,
        report_dir: Path | None = None,
    ) -> CommandResult:
        env = {name: os.environ[name] for name in _ALLOWED_ENV_VARS if name in os.environ}
        argv = expand_report_dir(args, str(report_dir) if report_dir is not None else None)
        try:
            completed = subprocess.run(  # noqa: S603 -- argv list, never shell=True
                [executable, *argv],
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

    def _changes(self) -> list[_Change]:
        if self.evaluating:
            # After start_evaluation() the workspace is the control plane's,
            # not the agent's: comparing it against the base would report
            # the gate's view, never what the agent did.
            raise RuntimeError("changed_paths/collect_diff must be read before start_evaluation()")
        return _tree_changes(
            self.base_repo_path, self.workdir, base_excluded=self._excluded_from_base
        )

    def start_evaluation(self, *, protected: Sequence[str]) -> None:
        """See ``Sandbox.start_evaluation``. Built from the BASE, never by
        copying the agent's workspace and "restoring" the protected paths:
        a protected path the agent created (a new conftest.py, a symlink)
        must not survive, and there is nothing to forget to restore.

        Carried over from the agent's workspace: added/modified regular
        files and deletions, outside ``protected``. Not carried over, and
        recorded in ``discarded_changes``: anything under ``protected``,
        and every symlink or special file the agent left -- ``patch_file``
        cannot create one, so it is already an ``untracked_modification``
        (FAIL), and carrying it would let a gate follow it to a host file.
        """
        changes = self._changes()
        tmp = Path(tempfile.mkdtemp(prefix="aigis-eval-"))
        evaldir = tmp / "workspace"
        shutil.copytree(
            self.base_repo_path,
            evaldir,
            symlinks=True,
            ignore=self._eval_copy_ignore,
        )
        discarded: list[dict[str, str]] = []
        for change in changes:
            if any(path_matches_protected(change.path, entry) for entry in protected):
                discarded.append({"path": change.path, "reason": "protected_path"})
                continue
            target = evaldir / change.path
            if change.work is None:
                _remove_entry(target)
            elif change.work.kind == "file":
                _remove_entry(target)
                _make_parent_dirs(target, evaldir)
                target.write_bytes(change.work.payload)  # type: ignore[arg-type]
            else:
                discarded.append({"path": change.path, "reason": f"{change.work.kind}_not_carried"})
        agent_tmp = self.workdir.parent
        self._workdir = evaldir
        self.evaluating = True
        self.discarded_changes = discarded
        shutil.rmtree(agent_tmp, ignore_errors=True)

    def _eval_copy_ignore(self, dirpath: str, names: list[str]) -> list[str]:
        """Exactly the set create() skipped (forbidden paths, unsafe base
        symlinks), without re-deciding or re-recording it.
        """
        rel_dir = Path(dirpath).resolve().relative_to(self.base_repo_path)
        return [name for name in names if self._excluded_from_base((rel_dir / name).as_posix())]

    def collect_diff(self) -> str:
        return _render_diff(self._changes())

    def changed_paths(self) -> list[str]:
        """Every path that differs between the base repo and the workspace,
        observed on the filesystem -- not taken from the agent's tool log
        (P0 D4). Additions, deletions, content changes and type changes
        (file <-> symlink <-> directory) all count; a rename is a deletion
        plus an addition. Symlinks are compared as links (their target
        string), never followed. Same comparison as ``collect_diff``, so
        ``diff.patch`` and this list cannot diverge.
        """
        return [change.path for change in self._changes()]

    def destroy(self) -> None:
        if self._workdir is not None:
            shutil.rmtree(self._workdir.parent, ignore_errors=True)
            self._workdir = None


def _remove_entry(target: Path) -> None:
    """Removes whatever sits at ``target`` (file, symlink or directory)
    without following a link. A missing path, or one whose parent is no
    longer a directory, is already gone.
    """
    try:
        st = target.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return
    if stat.S_ISDIR(st.st_mode):
        shutil.rmtree(target)
    else:
        target.unlink()


def _make_parent_dirs(target: Path, root: Path) -> None:
    """Like ``mkdir(parents=True)``, but a non-directory sitting where a
    parent directory must go (the agent turned a file into a directory) is
    removed first instead of raising.
    """
    current = root
    for part in target.relative_to(root).parts[:-1]:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            current.unlink()
        current.mkdir(exist_ok=True)


def _apply_resource_limits() -> None:
    """``preexec_fn`` for POSIX: caps CPU time and address space for the
    sandboxed subprocess (THREAT-MODEL.md, "Resource exhaustion"). No PID or
    process limit here -- see below. Runs in the forked child before exec,
    so a limit here can never affect the parent. Not available on Windows --
    ``run_command`` only wires this in when ``os.name == "posix"``.

    Deliberately NO ``RLIMIT_NPROC``: it is a per-UID limit (every process
    and thread the user owns on the host counts against it), not a
    per-sandbox one. A value of 64 made any multi-threaded tool (ruff spawns
    one thread per core) crash with EAGAIN on a normal Linux host, while
    providing no real bound on the sandbox itself. The PID limit lives in
    ``DockerSandbox`` (``--pids-limit``), where it is scoped to the container.
    """
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (1 * 1024 * 1024 * 1024, 1 * 1024 * 1024 * 1024))


# Directories/suffixes that are execution byproducts, not agent-authored
# changes -- excluded from BOTH the diff and changed_paths() (one shared
# comparison, below), so e.g. a __pycache__/*.pyc or .pytest_cache created
# by running pytest never shows up as a changed file or as an
# untracked_modification, and a binary .pyc never reaches the UTF-8 decode.
_DIFF_IGNORED_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}
_DIFF_IGNORED_SUFFIXES = {".pyc", ".pyo"}


@dataclass(frozen=True)
class _Entry:
    """One path as seen with ``lstat`` -- never following a symlink.

    ``kind`` is "file", "symlink" or "other" (fifo, socket, device...).
    ``payload`` is the file's bytes, the symlink's target string, or b"".
    """

    kind: str
    payload: bytes | str


@dataclass(frozen=True)
class _Change:
    path: str
    base: _Entry | None
    work: _Entry | None


def _is_ignored(rel_parts: tuple[str, ...]) -> bool:
    if Path(rel_parts[-1]).suffix in _DIFF_IGNORED_SUFFIXES:
        return True
    return any(part in _DIFF_IGNORED_DIR_NAMES for part in rel_parts)


def _snapshot(root: Path, skip: Callable[[str], bool] | None = None) -> dict[str, _Entry]:
    """Every non-directory entry under ``root``, keyed by POSIX relative
    path. ``os.walk(followlinks=False)`` plus ``lstat``: a symlink -- to a
    file or to a directory, inside or outside the tree -- is recorded as a
    link and never opened, so neither the diff nor the hashes can pull in
    the content of a host file it points at.
    """
    entries: dict[str, _Entry] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        rel_dir = current.relative_to(root).parts
        # prune ignored directories; a symlinked directory is not descended
        # into by os.walk, but it IS a change we must record below.
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _DIFF_IGNORED_DIR_NAMES
            and not (skip and skip("/".join((*rel_dir, d))))
        ]
        for name in [*filenames, *(d for d in dirnames if (current / d).is_symlink())]:
            rel_parts = (*rel_dir, name)
            if _is_ignored(rel_parts) or (skip and skip("/".join(rel_parts))):
                continue
            full = current / name
            st = full.lstat()
            if stat.S_ISLNK(st.st_mode):
                entry = _Entry("symlink", os.readlink(full))
            elif stat.S_ISREG(st.st_mode):
                entry = _Entry("file", full.read_bytes())
            else:
                entry = _Entry("other", b"")
            entries["/".join(rel_parts)] = entry
    return entries


def _tree_changes(
    base: Path, workdir: Path, *, base_excluded: Callable[[str], bool] | None = None
) -> list[_Change]:
    """The single base-vs-workspace comparison behind both ``collect_diff``
    and ``changed_paths`` -- the plain-filesystem equivalent of
    ``git status``/``git diff`` for a base repo that may not itself be a
    git repository (the toy repos this sandbox runs against).
    """
    base_entries = _snapshot(base, base_excluded)
    work_entries = _snapshot(workdir)
    changes: list[_Change] = []
    for rel_path in sorted(base_entries.keys() | work_entries.keys()):
        before = base_entries.get(rel_path)
        after = work_entries.get(rel_path)
        if before != after:
            changes.append(_Change(rel_path, before, after))
    return changes


def _decode(entry: _Entry | None) -> str | None:
    if entry is None or entry.kind != "file":
        return None
    try:
        return entry.payload.decode("utf-8")  # type: ignore[union-attr]
    except UnicodeDecodeError:
        return None


def _describe(entry: _Entry | None) -> str:
    if entry is None:
        return "absent"
    if entry.kind == "symlink":
        return f"symlink -> {entry.payload}"
    return entry.kind


def _render_diff(changes: list[_Change]) -> str:
    chunks: list[str] = []
    for change in changes:
        rel_path = change.path
        if "symlink" in (getattr(change.base, "kind", None), getattr(change.work, "kind", None)):
            # Describe the link, never its target's content.
            chunks.append(
                f"Symlink change {rel_path}: {_describe(change.base)} => {_describe(change.work)}"
            )
            continue
        base_text = _decode(change.base)
        work_text = _decode(change.work)
        if base_text is None or work_text is None:
            chunks.append(f"Binary files a/{rel_path} and b/{rel_path} differ")
            continue
        diff = difflib.unified_diff(
            base_text.splitlines(keepends=True),
            work_text.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
        chunks.append("".join(diff))
    return "\n".join(chunks)


__all__ = ["LocalCowSandbox", "SandboxPathError"]
