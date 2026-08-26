"""AIGIS Control Plane — CLI entry point.

Thin argument-parsing shell around ``orchestrator.run_task``: everything
that actually does something (Policy Engine, Sandbox, Quality Gates,
Evidence Bundle, Decision Engine) was already built and tested in isolation
through Phase 5. This module only turns argv into one call against that
already-tested machinery, then reports the verdict.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aigis.domain import FinalDecision, TaskContract
from aigis.orchestrator import run_task
from aigis.providers.claude import ClaudeProvider
from aigis.sandbox.docker_sandbox import DockerSandbox
from aigis.sandbox.local_cow import LocalCowSandbox

# Matches common CLI convention (0 = success): FAIL and NEEDS_HUMAN are both
# "did not pass", but distinguishable by a caller/CI script that wants to
# treat "ask a human" differently from "definitely broken".
_EXIT_CODE_BY_DECISION = {
    FinalDecision.PASS: 0,
    FinalDecision.FAIL: 1,
    FinalDecision.NEEDS_HUMAN: 2,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aigis", description="AIGIS Control Plane")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser(
        "run", help="run a TaskContract against a repo with the Coder agent"
    )
    run.add_argument("contract", type=Path, help="path to a TaskContract JSON file")
    run.add_argument("repo", type=Path, help="path to the repo the agent will work on")
    run.add_argument("--sandbox", choices=["local", "docker"], default="local")
    run.add_argument("--evidence-dir", type=Path, default=Path("evidence"))
    run.add_argument(
        "--model", default=None, help="override the Claude model (else AIGIS_CLAUDE_MODEL)"
    )
    run.add_argument(
        "--json", action="store_true", help="print the Decision as JSON instead of a summary"
    )

    return parser


def _run(args: argparse.Namespace) -> int:
    contract = TaskContract.model_validate_json(args.contract.read_text(encoding="utf-8"))
    provider = ClaudeProvider(model=args.model)
    sandbox_factory = DockerSandbox if args.sandbox == "docker" else LocalCowSandbox

    _, decision, evidence = run_task(
        contract,
        args.repo,
        provider,
        sandbox_factory=sandbox_factory,
        evidence_base_dir=args.evidence_dir,
        model_provider="anthropic",
        model=provider.model,
    )

    if args.json:
        print(decision.model_dump_json(indent=2))
    else:
        print(f"[{decision.final.value}] {contract.task_id} -- {decision.reason}")
        print(f"evidence: {evidence.bundle_path}")

    return _EXIT_CODE_BY_DECISION[decision.final]


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    try:
        exit_code = _run(args)
    except RuntimeError as exc:
        # Missing ANTHROPIC_API_KEY, a Docker daemon that isn't running,
        # etc. -- a setup problem, not a task verdict, so it gets its own
        # exit code rather than colliding with FAIL/NEEDS_HUMAN and gets a
        # one-line message instead of a raw traceback.
        print(f"aigis: {exc}", file=sys.stderr)
        exit_code = 3
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
