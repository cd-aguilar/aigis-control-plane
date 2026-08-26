import sys
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
