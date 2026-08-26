from pathlib import Path

import pytest

from aigis.sandbox.docker_sandbox import DockerSandbox, build_docker_run_argv

# --- build_docker_run_argv: pure, testable without a Docker daemon ------------


def test_argv_disables_network() -> None:
    argv = build_docker_run_argv(
        image="python:3.11-slim",
        workdir_host_path="/tmp/x",
        executable="pytest",
        args=["tests/"],
    )
    assert "--network" in argv
    assert argv[argv.index("--network") + 1] == "none"


def test_argv_runs_as_non_root() -> None:
    argv = build_docker_run_argv(
        image="python:3.11-slim", workdir_host_path="/tmp/x", executable="pytest", args=[]
    )
    assert "--user" in argv
    assert argv[argv.index("--user") + 1] == "1000:1000"


def test_argv_is_read_only_with_a_tmpfs_for_tmp() -> None:
    argv = build_docker_run_argv(
        image="python:3.11-slim", workdir_host_path="/tmp/x", executable="pytest", args=[]
    )
    assert "--read-only" in argv
    assert "--tmpfs" in argv
    assert argv[argv.index("--tmpfs") + 1] == "/tmp"


def test_argv_applies_resource_limits() -> None:
    argv = build_docker_run_argv(
        image="python:3.11-slim",
        workdir_host_path="/tmp/x",
        executable="pytest",
        args=[],
        memory="256m",
        cpus="2",
        pids_limit=32,
    )
    assert argv[argv.index("--memory") + 1] == "256m"
    assert argv[argv.index("--cpus") + 1] == "2"
    assert argv[argv.index("--pids-limit") + 1] == "32"


def test_argv_mounts_workdir_readwrite_and_sets_working_dir() -> None:
    argv = build_docker_run_argv(
        image="python:3.11-slim",
        workdir_host_path="/host/workspace",
        executable="pytest",
        args=[],
    )
    assert "-v" in argv
    assert argv[argv.index("-v") + 1] == "/host/workspace:/workspace:rw"
    assert "-w" in argv
    assert argv[argv.index("-w") + 1] == "/workspace"


def test_argv_ends_with_image_then_executable_then_args() -> None:
    argv = build_docker_run_argv(
        image="python:3.11-slim",
        workdir_host_path="/tmp/x",
        executable="pytest",
        args=["-v", "tests/"],
    )
    assert argv[-4:] == ["python:3.11-slim", "pytest", "-v", "tests/"]


def test_argv_never_contains_a_shell_string() -> None:
    # every element is a discrete argv entry -- nothing here should ever be
    # handed to a shell, matching the ToolRequest-level guarantee.
    argv = build_docker_run_argv(
        image="python:3.11-slim", workdir_host_path="/tmp/x", executable="pytest", args=["tests/"]
    )
    assert all(isinstance(part, str) and "&&" not in part and ";" not in part for part in argv)


# --- availability check ---------------------------------------------------------


def test_is_available_returns_bool_without_raising() -> None:
    # Docker is very likely absent in the CI/dev sandbox this runs in --
    # the point of this test is that is_available() degrades to False
    # instead of raising, not that Docker is actually present.
    assert isinstance(DockerSandbox.is_available(), bool)


def test_run_command_raises_clear_error_when_docker_unavailable(tmp_path: Path) -> None:
    if DockerSandbox.is_available():
        pytest.skip("Docker is available in this environment; nothing to assert here")

    sandbox = DockerSandbox(str(tmp_path))
    sandbox.create()
    try:
        with pytest.raises(RuntimeError, match="Docker daemon"):
            sandbox.run_command("pytest", [], timeout_seconds=5)
    finally:
        sandbox.destroy()


@pytest.mark.skipif(not DockerSandbox.is_available(), reason="Docker daemon not available")
def test_run_command_executes_inside_container(tmp_path: Path) -> None:  # pragma: no cover
    sandbox = DockerSandbox(str(tmp_path))
    sandbox.create()
    try:
        result = sandbox.run_command(
            "python", ["-c", "print('hi from container')"], timeout_seconds=30
        )
        assert result.exit_code == 0
        assert "hi from container" in result.stdout
    finally:
        sandbox.destroy()
