# aigis-control-plane

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
- **Sandbox** — an ephemeral, isolated copy of the repo (copy-on-write locally,
  or a network-disabled, non-root, read-only-root Docker container) is where
  an ALLOWed request actually runs. A DENY never touches it.
- **Quality Gates** — `pytest`/`ruff` run *inside* the sandbox and are graded
  from their own structured JSON output, never from regex over stdout.
- **Evidence Bundle** — every run persists to `evidence/<run-id>/`: diff,
  structured test/lint reports, policy decisions, environment metadata, and a
  SHA-256 hash of every artifact for integrity.
- **Decision Engine** — computes `contract_valid ∧ policy_ok ∧ tests_pass ∧
  lint_pass ∧ scope_ok ∧ resource_limits_ok ⇒ PASS`. A blocked action
  (`DENY`) doesn't fail the run by itself — the control worked as intended.
  An ambiguous state (missing gate, `REQUIRE_HUMAN`) escalates to a human
  instead of guessing.

Full spec, threat model, and section-by-section detail:
**[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**.

## Status

> Phases 0–4 done. Domain layer (`TaskContract`, `ToolRequest`,
> `PolicyDecision`, `Attempt`, `TaskState`, `GateResult`, `Evidence`,
> `Decision`, `AgentClaim`) as Pydantic models with the Decision formula
> enforced structurally, not just documented. Agent Runtime (reducer +
> provider protocol) with a real `ClaudeProvider` adapter. Policy Engine
> (deterministic ALLOW/DENY/REQUIRE_HUMAN) in front of a real Sandbox
> (`LocalCowSandbox` + a `DockerSandbox` verified end-to-end against an
> actual Docker daemon: no network, non-root, read-only + tmpfs, resource
> caps). Executable Quality Gates (`pytest`/`ruff` inside the sandbox, graded
> from structured JSON), a real Evidence Bundle writer, and a fail-closed
> Decision Engine. **158 unit tests green, `ruff check` clean.**
>
> Not implemented yet: the Security Evaluation Suite (prompt injection,
> secret access, path traversal, command injection, resource exhaustion —
> Phase 5) and end-to-end CLI integration (Phase 6).

## Repo layout

```text
src/aigis/
  domain/      TaskContract, TaskState, Attempt, Evidence, Decision (Pydantic)
  agent/       Agent Runtime, reducer, tool schemas
  providers/   Claude adapter
  policy/      Policy Engine + policy.yaml
  sandbox/     LocalCowSandbox, DockerSandbox
  evaluation/  Quality Gates (pytest/ruff), Decision Engine
  evidence/    Evidence Bundle writer
  cli.py
tests/   docs/   examples/
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
