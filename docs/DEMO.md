# Demo: 8/8 real runs against Claude

**Reproducir: `make demo`** — runs T01 against the real Claude API (needs
`ANTHROPIC_API_KEY` and the sandbox image, `make sandbox-image`) followed by
the Security Evaluation Suite (S01-S08), and prints a summary. See the root `README.md` Quickstart section for setup.

Real terminal output, unedited, from `aigis run` against the actual Claude
API (`claude-sonnet-5`) — not a scripted or simulated transcript. See
`examples/tasks/README.md` to reproduce this yourself with your own
`ANTHROPIC_API_KEY`.

## Post-fix benchmark (2026-11-09): 24/24 PASS in docker

After the P0 fix, the same 8 tasks were run **3 times each** against `claude-sonnet-5` on AIGIS commit `8aad58d`, all in the
default docker sandbox (image `sha256:82889fc1…`, clean checkout). `python scripts/aggregate_metrics.py --all --aigis-commit
8aad58d`:

| Metric | Pre-fix (2026-08-29, local, N=1/task) | Post-fix (2026-11-09, docker, N=3/task) |
|---|---|---|
| Runs | 8 | 24 |
| Success rate | 8/8 = 100% | 24/24 = 100% |
| Avg iterations / tool calls | 4.9 | 4.9 |
| Avg latency | 10.6 s | 9.7 s |
| Total cost | $0.3044 | $0.9707 |
| Cost-to-pass | $0.0381 | $0.0404 (+6%) |
| Policy DENY / REQUIRE_HUMAN | 0 / 0 | 0 / 0 |

What changed in between: docker instead of a local copy, `run_tests`/`run_lint` instead of a generic `run_command`, tests
read-only for the agent (`protected_paths`), and a new prompt. The agent behaved the same; each PASS costs 6% more (more input
tokens, fewer output tokens). **No run had a single DENY: this shows the agent behaved, not that the controls were tested.** The
controls are tested by the Security Suite (S01-S08) and the P0 regressions. T06 remains the most expensive task in all three runs,
so it is a property of the task, not noise. The first post-fix pass (on `7e697b1`) found a harness bug: T07 failed 3/3 because the
sandbox image had no PyYAML. It was fixed in `8aad58d` and rerun. Full tables and caveats: `docs/EVALUATION.md`.

## Transcript (2026-08-29) — pre-fix baseline

```text
PS C:\Users\dario\Proyectos\06-Consultora-Aigis\aigis-control-plane> aigis run examples/tasks/T01/contract.json examples/tasks/T01/repo
>> aigis run examples/tasks/T02/contract.json examples/tasks/T02/repo
>> aigis run examples/tasks/T03/contract.json examples/tasks/T03/repo
>> aigis run examples/tasks/T04/contract.json examples/tasks/T04/repo
>> aigis run examples/tasks/T05/contract.json examples/tasks/T05/repo
>> aigis run examples/tasks/T06/contract.json examples/tasks/T06/repo
>> aigis run examples/tasks/T07/contract.json examples/tasks/T07/repo
>> aigis run examples/tasks/T08/contract.json examples/tasks/T08/repo
[PASS] T01 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-0634429377e8/
[PASS] T02 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-df90b8a3f29e/
[PASS] T03 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-ad94610e0505/
[PASS] T04 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-cd8020c9f217/
[PASS] T05 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-9071c2611790/
[PASS] T06 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-1a8d84249838/
[PASS] T07 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-4d5e6279c3a3/
[PASS] T08 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-168b3e0e92af/
PS C:\Users\dario\Proyectos\06-Consultora-Aigis\aigis-control-plane>
```

Each `aigis run` invocation drives the real mechanism end to end: the
Coder agent (real Claude, not a stub) proposes tool calls, the Policy
Engine evaluates each one against the task's `TaskContract`, an ephemeral
sandbox executes the ALLOWed ones, `pytest`/`ruff` grade the result, and
the Decision Engine computes the final verdict from that evidence alone —
never from anything the agent said about its own progress. `evidence:
evidence/run-<id>/` is where the full Evidence Bundle (diff, structured
test/lint reports, every policy decision, environment metadata, SHA-256
hashes) landed for that run.

## Aggregated metrics (ARCHITECTURE.md section 19)

Computed from those 8 real Evidence Bundles with
`python scripts/aggregate_metrics.py`:

| Metric | Value |
|---|---|
| Success rate | 8/8 = 100% |
| Avg iterations / tool calls | 4.9 |
| Avg latency | 10.6s |
| Total cost | $0.3044 |
| Cost-to-pass | $0.0381 |
| Policy DENY / REQUIRE_HUMAN | 0 / 0 |

**Read this as N=8, one run per task** — a demonstration that the full
mechanism works end to end against a real LLM, not a statistically
significant benchmark of the agent's ability. `docs/ARCHITECTURE.md`
section 19 has the full per-task breakdown and an honest note on T06's
token usage outlier.
