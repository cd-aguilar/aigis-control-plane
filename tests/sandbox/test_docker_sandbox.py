import json
import os
import subprocess
from pathlib import Path

import pytest

from aigis.evaluation.gates import PytestGate, RuffGate
from aigis.sandbox import docker_sandbox
from aigis.sandbox.base import REPORT_DIR_TOKEN
from aigis.sandbox.docker_sandbox import (
    CONTAINER_REPORT_DIR,
    DockerSandbox,
    SandboxImageError,
    build_docker_run_argv,
    container_user,
)


def _argv(**overrides) -> list[str]:
    fields = {
        "image": "sha256:abc",
        "workdir_host_path": "/host/workspace",
        "executable": "pytest",
        "args": ["tests/"],
    }
    fields.update(overrides)
    return build_docker_run_argv(**fields)


def _value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


# --- build_docker_run_argv: pure, testable without a Docker daemon ------------


def test_argv_disables_network() -> None:
    assert _value(_argv(), "--network") == "none"


def test_argv_drops_all_capabilities_and_privilege_escalation() -> None:
    argv = _argv()
    assert _value(argv, "--cap-drop") == "ALL"
    assert _value(argv, "--security-opt") == "no-new-privileges"


def test_argv_runs_as_the_given_non_root_user() -> None:
    assert _value(_argv(), "--user") == "1000:1000"
    assert _value(_argv(user="1001:121"), "--user") == "1001:121"


def test_argv_is_read_only_with_a_tmpfs_for_tmp() -> None:
    argv = _argv()
    assert "--read-only" in argv
    assert _value(argv, "--tmpfs") == "/tmp"


def test_argv_applies_resource_limits() -> None:
    argv = _argv(memory="256m", cpus="2", pids_limit=32)
    assert _value(argv, "--memory") == "256m"
    assert _value(argv, "--cpus") == "2"
    assert _value(argv, "--pids-limit") == "32"


def test_argv_mounts_the_workspace_read_only_and_nothing_else_by_default() -> None:
    argv = _argv()
    mounts = [argv[i + 1] for i, part in enumerate(argv) if part == "-v"]
    assert mounts == ["/host/workspace:/workspace:ro"]
    assert _value(argv, "-w") == "/workspace"


def test_argv_mounts_the_report_dir_rw_as_a_second_mount() -> None:
    argv = _argv(report_dir_host_path="/host/reports")
    mounts = [argv[i + 1] for i, part in enumerate(argv) if part == "-v"]
    assert mounts == ["/host/workspace:/workspace:ro", f"/host/reports:{CONTAINER_REPORT_DIR}:rw"]


def test_argv_disables_bytecode_writes() -> None:
    argv = _argv()
    envs = [argv[i + 1] for i, part in enumerate(argv) if part == "-e"]
    assert "PYTHONDONTWRITEBYTECODE=1" in envs


def test_argv_ends_with_image_then_executable_then_args() -> None:
    argv = _argv(image="sha256:abc", args=["-v", "tests/"])
    assert argv[-4:] == ["sha256:abc", "pytest", "-v", "tests/"]


def test_argv_never_contains_a_shell_string() -> None:
    assert all(isinstance(part, str) and "&&" not in part and ";" not in part for part in _argv())


# --- container user (UID fix) ----------------------------------------------------


def test_container_user_is_the_host_user_when_not_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_sandbox.os, "getuid", lambda: 1001, raising=False)
    monkeypatch.setattr(docker_sandbox.os, "getgid", lambda: 121, raising=False)
    assert container_user() == "1001:121"


def test_container_user_falls_back_to_1000_for_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_sandbox.os, "getuid", lambda: 0, raising=False)
    monkeypatch.setattr(docker_sandbox.os, "getgid", lambda: 0, raising=False)
    assert container_user() == "1000:1000"


def test_container_user_falls_back_to_1000_without_uids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(docker_sandbox.os, "getuid", raising=False)
    assert container_user() == "1000:1000"


# --- image verification (no daemon: docker CLI faked) ----------------------------


class _FakeDocker:
    def __init__(self, image_id: str | None) -> None:
        self.image_id = image_id
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], *, timeout: int = 30):
        self.calls.append(args)
        if args[0] == "version":  # is_available(): the daemon answers
            return subprocess.CompletedProcess(args, 0, "29.0\n", "")
        if self.image_id is None:
            return subprocess.CompletedProcess(args, 1, "", "No such image")
        return subprocess.CompletedProcess(args, 0, self.image_id + "\n", "")


def _fake_docker(monkeypatch: pytest.MonkeyPatch, fake: _FakeDocker) -> None:
    """No daemon needed: the docker CLI and the binary lookup are faked (a
    runner without the docker binary at all must still run these)."""
    monkeypatch.setattr(docker_sandbox, "_docker", fake)
    monkeypatch.setattr(docker_sandbox.shutil, "which", lambda name: "/usr/bin/docker")


def test_verify_image_pins_the_expected_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fake_docker(monkeypatch, _FakeDocker("sha256:good"))
    sandbox = DockerSandbox(tmp_path, expected_image_id="sha256:good")
    assert sandbox.verify_image() == "sha256:good"
    assert sandbox.image_id == "sha256:good"


def test_verify_image_rejects_a_different_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_docker(monkeypatch, _FakeDocker("sha256:retagged"))
    sandbox = DockerSandbox(tmp_path, expected_image_id="sha256:good")
    with pytest.raises(SandboxImageError, match="expected sha256:good"):
        sandbox.verify_image()


def test_verify_image_rejects_a_missing_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_docker(monkeypatch, _FakeDocker(None))
    with pytest.raises(SandboxImageError, match="make sandbox-image"):
        DockerSandbox(tmp_path, expected_image_id="sha256:good").verify_image()


def test_expected_image_id_comes_from_env_then_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    id_file = tmp_path / ".image-id"
    monkeypatch.setattr(docker_sandbox, "IMAGE_ID_FILE", id_file)
    monkeypatch.delenv(docker_sandbox.IMAGE_ID_ENV, raising=False)
    with pytest.raises(SandboxImageError, match="no expected sandbox image ID"):
        DockerSandbox(tmp_path).expected_image_id()
    id_file.write_text("sha256:from-file\n", encoding="utf-8")
    assert DockerSandbox(tmp_path).expected_image_id() == "sha256:from-file"
    monkeypatch.setenv(docker_sandbox.IMAGE_ID_ENV, "sha256:from-env")
    assert DockerSandbox(tmp_path).expected_image_id() == "sha256:from-env"
    assert DockerSandbox(tmp_path, expected_image_id="sha256:arg").expected_image_id() == (
        "sha256:arg"
    )


# --- availability check ---------------------------------------------------------


def test_is_available_returns_bool_without_raising() -> None:
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


# --- real containers (docker_ready: skip locally, FAIL in CI) --------------------


def _repo(root: Path) -> Path:
    files = {
        "src/calculator.py": "def subtract(a, b):\n    return a - b\n",
        "tests/test_calculator.py": (
            "from calculator import subtract\n\n\ndef test_subtract():\n"
            "    assert subtract(5, 3) == 2\n"
        ),
        "pytest.ini": "[pytest]\npythonpath = src\n",
        "data.txt": "readable from the container\n",
        # Explicit rule selection, like every benchmark repo: ruff 0.16's
        # default set includes EXE, and Docker Desktop on Windows shows
        # every bind-mounted file as 0777 (EXE002 on each one).
        "ruff.toml": '[lint]\nselect = ["E", "F"]\n',
    }
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")
    return root


@pytest.fixture
def real_sandbox(docker_ready: None, tmp_path: Path):
    sandbox = DockerSandbox(_repo(tmp_path / "repo"))
    sandbox.create()
    try:
        yield sandbox
    finally:
        sandbox.destroy()


def test_container_can_list_and_read_the_workspace(real_sandbox: DockerSandbox) -> None:
    """The UID bug: with a host uid != the container's, listdir/open used to
    fail with Permission denied. A print() alone never caught it."""
    script = (
        "import os, json; print(json.dumps({'ls': sorted(os.listdir('.')), "
        "'data': open('data.txt').read(), 'uid': os.getuid()}))"
    )
    result = real_sandbox.run_command("python", ["-c", script], timeout_seconds=60)
    assert result.exit_code == 0, result.stderr
    seen = json.loads(result.stdout)
    assert {"src", "tests", "pytest.ini", "data.txt"} <= set(seen["ls"])
    assert seen["data"] == "readable from the container\n"
    assert seen["uid"] != 0


def test_container_cannot_write_the_workspace(real_sandbox: DockerSandbox) -> None:
    script = "open('planted.txt', 'w').write('x')"
    result = real_sandbox.run_command("python", ["-c", script], timeout_seconds=60)
    assert result.exit_code != 0
    assert "Read-only file system" in result.stderr
    assert not (real_sandbox.workdir / "planted.txt").exists()


def test_container_has_no_network(real_sandbox: DockerSandbox) -> None:
    script = (
        "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('connected')\nexcept OSError as exc:\n    print('blocked', exc)\n"
    )
    result = real_sandbox.run_command("python", ["-c", script], timeout_seconds=60)
    assert "blocked" in result.stdout


def test_report_dir_is_the_only_writable_mount(real_sandbox: DockerSandbox, tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    result = real_sandbox.run_command(
        "python",
        ["-c", f"open('{REPORT_DIR_TOKEN}/r.txt', 'w').write('ok')"],
        timeout_seconds=60,
        report_dir=reports,
    )
    assert result.exit_code == 0, result.stderr
    assert (reports / "r.txt").read_text(encoding="utf-8") == "ok"


def test_real_gates_run_in_the_container(real_sandbox: DockerSandbox) -> None:
    """D3's pending docker case: PytestGate's report lands on the
    /aigis-report mount and is graded; nothing is written to the workspace."""
    before = sorted(p.relative_to(real_sandbox.workdir) for p in real_sandbox.workdir.rglob("*"))
    pytest_result = PytestGate().run(real_sandbox)
    ruff_result = RuffGate().run(real_sandbox)
    assert pytest_result.infrastructure_error is None, pytest_result.details
    assert pytest_result.passed is True, pytest_result.details
    assert ruff_result.passed is True, ruff_result.details
    after = sorted(p.relative_to(real_sandbox.workdir) for p in real_sandbox.workdir.rglob("*"))
    assert after == before


def test_timeout_kills_the_container(real_sandbox: DockerSandbox) -> None:
    result = real_sandbox.run_command(
        "python", ["-c", "import time; time.sleep(60)"], timeout_seconds=5
    )
    assert result.timed_out is True
    running = subprocess.run(
        ["docker", "ps", "-q", "--filter", "ancestor=" + str(real_sandbox.image_id)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert running.stdout.strip() == ""


def test_a_retagged_image_is_refused(docker_ready: None, tmp_path: Path) -> None:
    sandbox = DockerSandbox(_repo(tmp_path / "repo"), expected_image_id="sha256:" + "0" * 64)
    sandbox.create()
    try:
        with pytest.raises(SandboxImageError, match="expected sha256:0000"):
            sandbox.run_command("python", ["-V"], timeout_seconds=30)
    finally:
        sandbox.destroy()


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_container_reads_a_0700_workspace(real_sandbox: DockerSandbox) -> None:
    os.chmod(real_sandbox.workdir, 0o700)
    result = real_sandbox.run_command(
        "python", ["-c", "import os; os.listdir('.')"], timeout_seconds=60
    )
    assert result.exit_code == 0, result.stderr
