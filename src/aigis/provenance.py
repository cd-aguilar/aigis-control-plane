"""Provenance for ``environment.json`` (P0 D5): which code, which repo, which
interpreter produced a run.

Kept apart from the orchestrator because it shells out to ``git`` and must
fail soft: a field that cannot be determined is ``None``, never a guess.
In particular a commit is only recorded when the directory *is* the git
root -- ``examples/tasks/T01/repo`` lives inside the AIGIS repo, and
``git rev-parse HEAD`` there would silently return AIGIS's own commit.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

import aigis

# src/aigis/__init__.py -> repo root (an editable install / a checkout)
_AIGIS_ROOT = Path(aigis.__file__).resolve().parents[2]


def _git(path: Path, *args: str) -> str | None:
    if shutil.which("git") is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603, S607 -- argv list
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def git_commit_of(path: Path) -> str | None:
    """HEAD of ``path`` if ``path`` is the root of a git work tree, else
    None. Uncommitted changes are not reflected: the commit is the base the
    tree started from."""
    path = Path(path)
    toplevel = _git(path, "rev-parse", "--show-toplevel")
    if toplevel is None or Path(toplevel).resolve() != path.resolve():
        return None
    return _git(path, "rev-parse", "HEAD")


def aigis_commit() -> str | None:
    """The commit of the AIGIS checkout that is running, or None (e.g. an
    installed wheel, no git)."""
    return git_commit_of(_AIGIS_ROOT)


def python_version() -> str:
    """The control plane's interpreter. In docker mode the graded code runs
    on the sandbox image's interpreter, identified by ``sandbox_image_digest``."""
    return platform.python_version()


__all__ = ["aigis_commit", "git_commit_of", "python_version"]
