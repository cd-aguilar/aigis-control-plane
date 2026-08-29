# Demo: 8/8 real runs against Claude

Real terminal output, unedited, from `aigis run` against the actual Claude
API (`claude-sonnet-5`) — not a scripted or simulated transcript. See
`examples/tasks/README.md` to reproduce this yourself with your own
`ANTHROPIC_API_KEY`.

## Transcript (2026-08-29)

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
