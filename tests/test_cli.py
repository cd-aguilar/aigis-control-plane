from __future__ import annotations

import json
from pathlib import Path

import pytest

from aigis.cli import _build_parser, _run, main
from aigis.domain import Decision, EnvironmentMetadata, Evidence, FinalDecision

_CONTRACT_JSON = {
    "task_id": "T01",
    "description": "d",
    "allowed_paths": ["src/"],
    "success_criteria": ["ok"],
    "required_gates": ["pytest"],
    "max_iterations": 5,
    "max_runtime_seconds": 60,
    "max_tool_calls": 10,
    "max_files_changed": 1,
}


class _FakeProvider:
    def __init__(self, *, model: str | None = None, max_tokens: int = 4096) -> None:
        self.model = model or "fake-model"


def _fake_decision(
    final: FinalDecision, *, tests_pass: bool = True, policy_ok: bool = True
) -> Decision:
    return Decision(
        run_id="r1",
        task_id="T01",
        contract_valid=True,
        policy_ok=policy_ok,
        tests_pass=tests_pass,
        lint_pass=True,
        scope_ok=True,
        resource_limits_ok=True,
        final=final,
        reason="stub reason",
    )


def _fake_evidence() -> Evidence:
    return Evidence(
        run_id="r1",
        task_id="T01",
        bundle_path="evidence/r1/",
        environment=EnvironmentMetadata(run_id="r1", model_provider="test", model="fake-model"),
    )


@pytest.fixture
def contract_and_repo(tmp_path: Path) -> tuple[Path, Path]:
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(_CONTRACT_JSON), encoding="utf-8")
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    return contract_path, repo_path


# --- argument parsing ------------------------------------------------------


def test_parser_defaults(contract_and_repo: tuple[Path, Path]) -> None:
    contract_path, repo_path = contract_and_repo
    args = _build_parser().parse_args(["run", str(contract_path), str(repo_path)])

    assert args.command == "run"
    assert args.contract == contract_path
    assert args.repo == repo_path
    assert args.sandbox == "local"
    assert args.json is False
    assert args.model is None


def test_parser_accepts_sandbox_model_and_json_flags(
    contract_and_repo: tuple[Path, Path],
) -> None:
    contract_path, repo_path = contract_and_repo
    args = _build_parser().parse_args(
        [
            "run",
            str(contract_path),
            str(repo_path),
            "--sandbox",
            "docker",
            "--json",
            "--model",
            "claude-x",
        ]
    )

    assert args.sandbox == "docker"
    assert args.json is True
    assert args.model == "claude-x"


def test_parser_rejects_unknown_sandbox_choice(contract_and_repo: tuple[Path, Path]) -> None:
    contract_path, repo_path = contract_and_repo
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["run", str(contract_path), str(repo_path), "--sandbox", "aws"])


# --- _run: exit codes and output, ClaudeProvider/run_task both mocked ------


def test_run_pass_prints_summary_and_returns_exit_code_zero(
    monkeypatch: pytest.MonkeyPatch, contract_and_repo: tuple[Path, Path], capsys
) -> None:
    contract_path, repo_path = contract_and_repo
    monkeypatch.setattr("aigis.cli.ClaudeProvider", _FakeProvider)
    monkeypatch.setattr(
        "aigis.cli.run_task",
        lambda *a, **k: (None, _fake_decision(FinalDecision.PASS), _fake_evidence()),
    )
    args = _build_parser().parse_args(["run", str(contract_path), str(repo_path)])

    exit_code = _run(args)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "evidence/r1/" in out


def test_run_fail_returns_exit_code_one(
    monkeypatch: pytest.MonkeyPatch, contract_and_repo: tuple[Path, Path]
) -> None:
    contract_path, repo_path = contract_and_repo
    monkeypatch.setattr("aigis.cli.ClaudeProvider", _FakeProvider)
    monkeypatch.setattr(
        "aigis.cli.run_task",
        lambda *a, **k: (
            None,
            _fake_decision(FinalDecision.FAIL, tests_pass=False),
            _fake_evidence(),
        ),
    )
    args = _build_parser().parse_args(["run", str(contract_path), str(repo_path)])

    assert _run(args) == 1


def test_run_needs_human_returns_exit_code_two(
    monkeypatch: pytest.MonkeyPatch, contract_and_repo: tuple[Path, Path]
) -> None:
    contract_path, repo_path = contract_and_repo
    monkeypatch.setattr("aigis.cli.ClaudeProvider", _FakeProvider)
    monkeypatch.setattr(
        "aigis.cli.run_task",
        lambda *a, **k: (
            None,
            _fake_decision(FinalDecision.NEEDS_HUMAN, policy_ok=False),
            _fake_evidence(),
        ),
    )
    args = _build_parser().parse_args(["run", str(contract_path), str(repo_path)])

    assert _run(args) == 2


def test_run_json_flag_prints_decision_as_json(
    monkeypatch: pytest.MonkeyPatch, contract_and_repo: tuple[Path, Path], capsys
) -> None:
    contract_path, repo_path = contract_and_repo
    monkeypatch.setattr("aigis.cli.ClaudeProvider", _FakeProvider)
    monkeypatch.setattr(
        "aigis.cli.run_task",
        lambda *a, **k: (None, _fake_decision(FinalDecision.PASS), _fake_evidence()),
    )
    args = _build_parser().parse_args(["run", str(contract_path), str(repo_path), "--json"])

    _run(args)

    printed = json.loads(capsys.readouterr().out)
    assert printed["final"] == "PASS"
    assert printed["run_id"] == "r1"


def test_run_passes_provider_model_and_sandbox_choice_through(
    monkeypatch: pytest.MonkeyPatch, contract_and_repo: tuple[Path, Path]
) -> None:
    """The CLI must forward the chosen sandbox factory and the provider's
    own resolved model string into run_task -- not silently default both,
    which would make --sandbox docker and --model a no-op.
    """
    contract_path, repo_path = contract_and_repo
    captured: dict[str, object] = {}

    def fake_run_task(contract, repo, provider, **kwargs):
        captured["sandbox_factory"] = kwargs["sandbox_factory"]
        captured["model"] = kwargs["model"]
        return None, _fake_decision(FinalDecision.PASS), _fake_evidence()

    monkeypatch.setattr("aigis.cli.ClaudeProvider", _FakeProvider)
    monkeypatch.setattr("aigis.cli.run_task", fake_run_task)
    args = _build_parser().parse_args(
        ["run", str(contract_path), str(repo_path), "--sandbox", "docker", "--model", "claude-x"]
    )

    _run(args)

    from aigis.sandbox.docker_sandbox import DockerSandbox

    assert captured["sandbox_factory"] is DockerSandbox
    assert captured["model"] == "claude-x"


def test_main_reports_missing_api_key_as_a_clean_error_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, contract_and_repo: tuple[Path, Path], capsys
) -> None:
    contract_path, repo_path = contract_and_repo
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(contract_path), str(repo_path)])

    assert exc_info.value.code == 3
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
