# aigis-control-plane

[![ci](https://github.com/cd-aguilar/aigis-control-plane/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/cd-aguilar/aigis-control-plane/actions/workflows/ci.yml)

**Evidence-Driven Agent Harness.** A security-first control plane for AI coding
agents that separates *what the agent can do* from *what it's authorized to
do* from *whether the task actually got done*.

## The problem

Coding agents can read repos, edit files, run commands, and iterate on
failures — but "the agent can do X" says nothing about whether it *should*,
and "the agent says it's done" says nothing about whether it's *true*. Most
agent harnesses let the LLM police itself: it decides which actions to try,
and its own final message is treated as the verdict. That collapses three
separate questions into one untrusted answer:

1. What is the agent capable of executing?
2. What is it actually authorized to touch, right now, for this task?
3. Did the task verifiably pass — determined by something other than the
   agent's own claim?

**AIGIS Control Plane's answer:** authority lives in the control plane, never
in the LLM.

```text
CAPABILITY  →  AUTHORIZATION  →  VERIFICATION
(agent proposes)  (Policy Engine decides)  (evidence decides)
```

> **The agent can claim it is done. The system decides whether it is true.**

Every tool call is a structured `ToolRequest` (never a shell string) evaluated
by a deterministic Policy Engine (deny-by-default ALLOW/DENY/REQUIRE_HUMAN)
before it ever reaches a sandbox. Everything the agent actually did is
captured as evidence — diffs, structured test/lint reports, policy decisions,
environment metadata — and a Decision Engine computes PASS/FAIL/NEEDS_HUMAN
from that evidence alone. The agent's own "I'm done" message is logged
separately and never read by the Decision Engine.

Implements the Evaluator-Optimizer pattern from Anthropic's [Building
Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
with deterministic evaluators instead of LLM-as-judge, plus the
[12-Factor Agents](https://github.com/humanlayer/12-factor-agents) principles.

## How it works

```text
TaskContract → Agent → ToolRequest → Policy Engine → Sandbox → Execution
    → Evidence → Quality Gates → Decision Engine → PASS / FAIL / NEEDS_HUMAN
```

- **TaskContract** — the only place scope (`allowed_paths`/`forbidden_paths`),
  circuit-breaker limits, and success criteria are declared. Nothing
  downstream may exceed it.
- **Policy Engine** — deterministic, external to the LLM. Fail-closed: a task
  with `risk_level: CRITICAL` denies everything, `HIGH` requires a human,
  before any path/command rule is even consulted.
- **Sandbox** — an ephemeral copy of the repo is where an ALLOWed request
  actually runs; a DENY never touches it. **By default a container**
  (since P0 D5): the AIGIS sandbox image verified by image ID, no network
  (`--network none`), no capabilities, non-root, read-only root and a
  read-only workspace mount. A local copy-on-write mode with *no*
  isolation exists only behind `--unsafe-local`, and every run in it is
  recorded as `isolation: none`.
- **Quality Gates** — `pytest`/`ruff` run *inside* the sandbox and are graded
  from their own structured JSON output, never from regex over stdout.
- **Evidence Bundle** — every run persists to `evidence/<run-id>/`: diff,
  structured test/lint reports, policy decisions, environment metadata, and a
  SHA-256 checksum of every artifact (detects accidental corruption only:
  unsigned and stored next to the artifacts, so not tamper-evidence).
- **Decision Engine** — computes `contract_valid ∧ policy_ok ∧ tests_pass ∧
  lint_pass ∧ scope_ok ∧ resource_limits_ok ⇒ PASS`. An ordinary blocked
  action (e.g. a file outside scope) doesn't fail the run by itself — the
  control worked as intended. A *security* DENY (path traversal, a
  forbidden path, patching a test or grader config) turns a would-be PASS
  into `NEEDS_HUMAN` (`deny_escalation`, on by default). An ambiguous state
  (missing gate, `REQUIRE_HUMAN`) escalates to a human instead of guessing.

Full spec and section-by-section detail:
**[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**. Threat model and OWASP
ASI Top 10 2026 mapping: **[`docs/THREAT-MODEL.md`](docs/THREAT-MODEL.md)**.
Security posture and controls: **[`docs/SECURITY.md`](docs/SECURITY.md)**.
Security evals, benchmark suite, and metrics:
**[`docs/EVALUATION.md`](docs/EVALUATION.md)**.

Real terminal output from 8/8 tasks run against the actual Claude API,
plus the metrics computed from that: **[`docs/DEMO.md`](docs/DEMO.md)**.

## Known limitations

> **Open P0 security finding (since 2026-09-22), partly fixed.** What the
> fix has closed so far: the agent has no generic command tool any more,
> only `run_tests`/`run_lint` with fixed profiles and no free arguments,
> and the generic allowlist is empty (D1); forbidden paths are no longer
> copied into the sandbox (D2); a write that bypasses `patch_file` is
> observed on the filesystem and fails the run (D4); tests, test/lint
> config and the pytest report are protected and taken from the base repo
> when the gates run (D3). The original proof of concept now ends in
> `FAIL`, not `PASS`. Since D5 the default sandbox is a container with
> no network and no view of the host (base repo included). What remains:
> the agent's own code still runs — pytest imports what it wrote, in
> `run_tests` and in the gate — so inside the container it can still
> tamper with its own grading (e.g. patch `_pytest`) and whatever it
> prints reaches the LLM. The post-fix benchmark (closing criterion 8) is
> still to be run. Until then AIGIS **cannot claim** to verify a task
> independently of the agent.
> Findings: [`docs/security/P0-review.md`](docs/security/P0-review.md).
> Fix design and closing criteria: [`docs/security/P0-design.md`](docs/security/P0-design.md).
> Remaining failing regressions (xfail strict): `tests/test_p0_regressions.py`.

- **`--unsafe-local` is not a sandbox.** It runs the agent's code as
  host subprocesses: host filesystem and network visible. It is explicit,
  warned about on stderr, recorded as `isolation: none` in
  `environment.json` and named in the decision's reason.
- **Docker mode needs the AIGIS sandbox image** (`make sandbox-image`).
  Since D5 it runs that image by its verified image ID (base pinned by
  digest, pytest/ruff pinned), with `--cap-drop ALL`, `no-new-privileges`,
  no network, a read-only root and a **read-only workspace mount**; reports
  go to a separate mount. A missing or different image means no run at all
  (`NEEDS_HUMAN`). Verified on Docker Desktop (Windows); CI runs the same
  container tests on a native Linux runner (uid 1001) and fails if Docker
  is missing (`AIGIS_REQUIRE_DOCKER=1`).
- **The graded code still runs inside the gate.** Since D3, tests,
  pytest/ruff config and any `conftest.py` are protected (read-only for
  the agent, always taken from the base repo when the gates run) and the
  pytest report is written outside the workspace. A skip/xfail produced
  by the code under test, or a `noqa` the agent wrote, no longer passes
  the gates. But pytest imports the
  agent's code, so that code runs in the gate's process (and in the
  agent's own `run_tests`) and could still tamper with the run from the
  inside; in local mode it also sees the host. Closing that needs process isolation
  between grader and graded code; it is a documented limit, not a guarantee
  ([`docs/SECURITY.md`](docs/SECURITY.md)).
- **Scope is observed only inside the workspace.** Since D4, `scope_ok`
  and `max_files_changed` come from comparing the workspace against the
  base repo, not from the agent's tool log, so a change that bypasses
  `patch_file` fails the run (`untracked_modification`). A local-mode
  command that writes *outside* the workspace, on the host, is not
  observed.
- **Evidence checksums are not tamper-evidence.** `hashes.json` is unsigned;
  signed receipts are planned, not built.
- **The 8/8 benchmark is a pre-fix baseline** (local sandbox, N=1-3 per
  task). It shows the mechanism runs end to end with a real LLM. It is not
  evidence that the controls contain an adversarial agent.
- **No conformance claims.** The OWASP ASI and AARM mappings in
  [`docs/THREAT-MODEL.md`](docs/THREAT-MODEL.md) are informal gap analyses.

## Status

> Phases 0–6 done (initial MVP scope complete). Domain layer (`TaskContract`, `ToolRequest`,
> `PolicyDecision`, `Attempt`, `TaskState`, `GateResult`, `Evidence`,
> `Decision`, `AgentClaim`) as Pydantic models with the Decision formula
> enforced structurally, not just documented. Agent Runtime (reducer +
> provider protocol) with a real `ClaudeProvider` adapter. Policy Engine
> (deterministic ALLOW/DENY/REQUIRE_HUMAN) in front of a real Sandbox
> (`DockerSandbox` by default since P0 D5 — no network, no capabilities,
> non-root, read-only root and workspace, resource caps, image verified by
> ID; container tests mandatory in CI — plus `LocalCowSandbox`, only behind
> `--unsafe-local`; see Known limitations). Executable Quality Gates (`pytest`/`ruff` inside the sandbox, graded
> from structured JSON), a real Evidence Bundle writer, and a fail-closed
> Decision Engine. A Security Evaluation Suite (since 2026-11-09 it also
> holds the P0 evals S07 Grader Tampering and S08 Untracked Modification,
> graded on the final Decision) — all 5 originally-planned
> evals (S01 Prompt Injection, S02 Unauthorized Secret Access, S03 Path
> Traversal, S04 Command Injection, S05 Resource Exhaustion) — drives the
> real Policy Engine + Sandbox (or, for S05, the contract's circuit
> breaker) end to end and grades containment as an ordinary `GateResult` —
> no separate code path for "security" in the Evidence Bundle or Decision
> Engine.
> An orchestrator (`run_task`) wires the whole mechanism into one call, and
> a real CLI (`aigis run <contract.json> <repo>`) is installed and wired to
> it. **All 8 functional benchmark tasks from section 18 (T01-T08) have run
> live against the real Claude API (`claude-sonnet-5`): 8/8 PASS** — T05
> with an adversarial decoy file outside scope, T07 with `config/`
> deliberately in scope instead of forbidden (contrast with T05). These
> are a **pre-fix baseline** (see Known limitations).
> `aigis.evaluation.metrics` + `scripts/aggregate_metrics.py` turn those
> real Evidence Bundles into the metrics section 19 asks for: 100% success
> rate, 4.9 average iterations/tool calls, 10.6s average latency, $0.30
> total cost, $0.038 cost-to-pass — reported honestly as N=8 (one run each),
> not a statistically significant benchmark.
> **447 tests collected (Windows with Docker Desktop: 439 passed, 8 platform
> skips, no P0 regression left in xfail), `ruff check` clean.** A minimal CI workflow (pytest + ruff on
> push/PR to `main`) is defined in `.github/workflows/ci.yml`.
>
> The initial MVP scope (ARCHITECTURE.md section 21) was completed on
> 2026-08-29; the open P0 above now blocks everything else. Still out of
> scope: Phase 7 (Production Hardening — human approval, GitHub write
> access, full CI/CD, a real Credential Broker, RBAC). See `examples/tasks/README.md` to run a benchmark task
> yourself, or `docs/EVALUATION.md` for the full results table.

## Quickstart with Dev Container

Fastest way to a working environment, Docker sandbox included: open this repo
in VS Code, run **Dev Containers: Reopen in Container** (needs the
[Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
and Docker Desktop on the host), and wait for the first build — it installs
Python 3.11, `docker-in-docker`, and runs `pip install -e ".[dev]"` for you.
Export `ANTHROPIC_API_KEY` on the host first; the container reads it from
there, never hardcoded. Then `pytest -q` should be green, `docker info`
should show a working daemon, and `make demo` runs the one-command portfolio
demo. See [`.devcontainer/README.md`](.devcontainer/README.md) for details.

## Repo layout

```text
src/aigis/
  domain/      TaskContract, TaskState, Attempt, Evidence, Decision (Pydantic)
  agent/       Agent Runtime, reducer, tool schemas
  providers/   Claude adapter
  policy/      Policy Engine + policy.yaml
  sandbox/     LocalCowSandbox, DockerSandbox
  evaluation/  Quality Gates (pytest/ruff), Decision Engine, Security Eval
               Suite, functional benchmark tasks (T01-T08), metrics
               aggregation (success rate, cost-to-pass, ...)
  evidence/    Evidence Bundle writer
  orchestrator.py   wires the whole mechanism into one run_task() call
  cli.py            `aigis run <contract.json> <repo>`
tests/   docs/   examples/tasks/   scripts/  (aggregate_metrics.py --per-task for N>1/task)
```

## Where this fits

Part of a five-project AI/security portfolio. The other four each tackle a
concrete security workflow — a SOC homelab
([`aigis-detect`](https://github.com/cd-aguilar/aigis-detect): SIEM/SOAR/DFIR
+ AI triage), a multi-agent alert-triage orchestrator
([`agent-orchestrator-soc`](https://github.com/cd-aguilar/agent-orchestrator-soc):
LangGraph + local RAG), a personal knowledge base
([`local-rag-second-brain`](https://github.com/cd-aguilar/local-rag-second-brain):
offline RAG over an Obsidian vault), and the portfolio site itself
([`aigis-cloud`](https://github.com/cd-aguilar/aigis-cloud)) that showcases
all of them.

**aigis-control-plane is the odd one out on purpose**: it isn't about a
specific security domain, it's the infrastructure question underneath all of
them — *once an AI agent can act, how do you keep it inside authorized
bounds and prove what it actually did?* Everything it builds (Policy Engine,
sandboxing, evidence, deterministic verification) is reusable by any of the
other agents in this portfolio, not only the toy coding-agent use case it
starts with (see `docs/ARCHITECTURE.md` section 26, "Evolución futura").
