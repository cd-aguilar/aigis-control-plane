import os
import sys
import time
from pathlib import Path

import pytest

from aigis.sandbox.local_cow import LocalCowSandbox, SandboxPathError


def test_create_copies_base_repo_without_touching_it(base_repo: Path) -> None:
    original_content = (base_repo / "src" / "math_utils.py").read_text(encoding="utf-8")
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        assert sandbox.read_file("src/math_utils.py") == original_content
        # mutate inside the sandbox, then confirm the base repo is untouched
        sandbox.write_file("src/math_utils.py", "changed")
        assert (base_repo / "src" / "math_utils.py").read_text(encoding="utf-8") == original_content
    finally:
        sandbox.destroy()


def test_read_file_missing_raises_file_not_found(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        with pytest.raises(FileNotFoundError):
            sandbox.read_file("src/does_not_exist.py")
    finally:
        sandbox.destroy()


def test_read_file_rejects_path_escaping_workdir(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        with pytest.raises(SandboxPathError):
            sandbox.read_file("../../etc/passwd")
    finally:
        sandbox.destroy()


def test_write_file_creates_parent_directories(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        sandbox.write_file("src/new/nested.py", "x = 1\n")
        assert sandbox.read_file("src/new/nested.py") == "x = 1\n"
    finally:
        sandbox.destroy()


def test_collect_diff_reports_changed_file(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        sandbox.write_file("src/math_utils.py", "def add(a, b):\n    return a + b\n")
        diff = sandbox.collect_diff()
        assert "math_utils.py" in diff
        assert "-    return a - b" in diff
        assert "+    return a + b" in diff
    finally:
        sandbox.destroy()


def test_collect_diff_is_empty_when_nothing_changed(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        assert sandbox.collect_diff() == ""
    finally:
        sandbox.destroy()


def test_destroy_removes_the_ephemeral_workdir(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    workdir = sandbox.workdir
    assert workdir.exists()
    sandbox.destroy()
    assert not workdir.exists()


def test_run_command_captures_stdout_and_exit_code(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        result = sandbox.run_command(
            sys.executable, ["-c", "print('hello from sandbox')"], timeout_seconds=10
        )
        assert result.exit_code == 0
        assert "hello from sandbox" in result.stdout
        assert result.timed_out is False
    finally:
        sandbox.destroy()


def test_run_command_reports_nonzero_exit_code(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        result = sandbox.run_command(
            sys.executable, ["-c", "import sys; sys.exit(3)"], timeout_seconds=10
        )
        assert result.exit_code == 3
    finally:
        sandbox.destroy()


def test_run_command_missing_executable_returns_result_not_exception(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        result = sandbox.run_command("definitely-not-a-real-binary", [], timeout_seconds=5)
        assert result.exit_code == 127
        assert "not found" in result.stderr
    finally:
        sandbox.destroy()


def test_run_command_enforces_timeout(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        result = sandbox.run_command(
            sys.executable, ["-c", "import time; time.sleep(5)"], timeout_seconds=1
        )
        assert result.timed_out is True
    finally:
        sandbox.destroy()


def test_run_command_runs_with_workdir_as_cwd(base_repo: Path) -> None:
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        result = sandbox.run_command(
            sys.executable, ["-c", "import os; print(os.getcwd())"], timeout_seconds=10
        )
        assert result.stdout.strip() == str(sandbox.workdir)
    finally:
        sandbox.destroy()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX resource limits only")
def test_run_command_allows_multithreaded_tools_under_posix_limits(base_repo: Path) -> None:
    # Regression: RLIMIT_NPROC=64 (per-UID, not per-sandbox) made ruff crash
    # with EAGAIN on Linux. 100 threads must be alive at the same time under
    # the sandbox limits (daemon threads, so a failed start() exits, not hangs).
    # Small stacks keep this about the thread COUNT, not RLIMIT_AS (1 GiB is
    # intentional, and 100 x 8 MiB default stacks would hit it on their own).
    script = (
        "import sys, threading\n"
        "threading.stack_size(256 * 1024)\n"
        "ev = threading.Event()\n"
        "try:\n"
        "    for _ in range(100):\n"
        "        threading.Thread(target=ev.wait, daemon=True).start()\n"
        "except RuntimeError as exc:\n"
        "    print(exc, file=sys.stderr); sys.exit(1)\n"
        "ev.set()\n"
        "print('ok')\n"
    )
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        result = sandbox.run_command(sys.executable, ["-c", script], timeout_seconds=20)
        assert result.exit_code == 0, result.stderr
        assert "ok" in result.stdout
    finally:
        sandbox.destroy()


_GRANDCHILD_SCRIPT = """
import subprocess, sys, time
grandchild = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"]
)  # inherits stdout/stderr: the pipes stay open while it lives
print(grandchild.pid, flush=True)
time.sleep(60)
"""


def _alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True  # no /proc (macOS): exists, can't tell a zombie apart
    return stat.rsplit(")", 1)[1].split()[0] != "Z"  # a zombie is dead


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups only")
def test_run_command_timeout_kills_grandchildren_and_does_not_hang(base_repo: Path) -> None:
    """Commit 14: with subprocess.run, a timeout killed only the direct
    child; the grandchild (60 s sleep, holding the inherited pipes) survived
    as an orphan. Now the whole process group is killed: the grandchild is
    gone, and reading the pipes after the kill does not wait for it (the
    call returns shortly after the timeout). Mutation check: with the old
    subprocess.run code this test fails on "survived the timeout"."""
    sandbox = LocalCowSandbox(base_repo)
    sandbox.create()
    try:
        started = time.monotonic()
        result = sandbox.run_command(sys.executable, ["-c", _GRANDCHILD_SCRIPT], timeout_seconds=2)
        elapsed = time.monotonic() - started
    finally:
        sandbox.destroy()
    assert result.timed_out and result.exit_code == -1
    assert elapsed < 15, f"run_command hung {elapsed:.1f}s past a 2s timeout"
    grandchild_pid = int(result.stdout.split()[0])
    deadline = time.monotonic() + 5
    while _alive(grandchild_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(grandchild_pid), f"grandchild {grandchild_pid} survived the timeout"


def test_create_twice_raises() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        sandbox = LocalCowSandbox(tmp)
        sandbox.create()
        try:
            with pytest.raises(RuntimeError):
                sandbox.create()
        finally:
            sandbox.destroy()
