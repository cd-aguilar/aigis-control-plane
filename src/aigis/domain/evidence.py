"""Evidence — the metadata record for one run's Evidence Bundle.

Per ARCHITECTURE.md section 13, the on-disk bundle is:

    evidence/<run-id>/
        manifest.json  task.json  trace.jsonl  state.json  events.jsonl
        diff.patch  test-report.json  lint-report.json  security-report.json
        environment.json  hashes.json  decision.json

This model does not hold the artifact contents themselves (those are
produced by the Sandbox/Quality Gates/Policy Engine in later phases) — it
holds the pointers and the reproducibility metadata (section 14) that let
someone reconstruct and compare runs later ("Model A vs Model B, Prompt v1
vs v2...") without re-reading every raw file.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from aigis.domain.quality_gate import GateResult


class EnvironmentMetadata(BaseModel):
    """``environment.json`` — everything needed to reconstruct the context
    of a run (section 14).
    """

    model_config = {"frozen": True}

    run_id: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_provider: str
    model: str
    model_version: str | None = None
    prompt_version: str | None = None
    agent_version: str | None = None
    task_contract_version: str | None = None
    policy_version: str | None = None

    git_commit: str | None = None
    sandbox_image: str | None = None
    sandbox_image_digest: str | None = None
    python_version: str | None = None
    dependency_lock_hash: str | None = None
    host_platform: str | None = None

    # Section 19 metrics ("token cost", "cost-to-pass") need these; None
    # for a Provider that doesn't expose a `usage_summary` (e.g. the
    # ScriptedProvider the Security Suite and orchestrator tests use, which
    # never calls a real LLM and has no tokens to report).
    total_input_tokens: int | None = Field(default=None, ge=0)
    total_output_tokens: int | None = Field(default=None, ge=0)


class Evidence(BaseModel):
    """Pointers into ``evidence/<run_id>/`` plus the gate results and
    environment metadata needed to evaluate and later audit the run.
    """

    model_config = {"frozen": True}

    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    bundle_path: str = Field(
        min_length=1, description="e.g. 'evidence/<run-id>/'"
    )

    diff_path: str | None = None
    test_report_path: str | None = None
    lint_report_path: str | None = None
    security_report_path: str | None = None
    trace_path: str | None = None
    events_path: str | None = None
    state_path: str | None = None
    task_path: str | None = None
    hashes_path: str | None = None

    environment: EnvironmentMetadata
    gate_results: list[GateResult] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def gate(self, gate_name: str) -> GateResult | None:
        return next((g for g in self.gate_results if g.gate_name == gate_name), None)

    def all_gates_passed(self) -> bool:
        return bool(self.gate_results) and all(g.passed for g in self.gate_results)
