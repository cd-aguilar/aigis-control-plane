# Contributing

## Before you commit

```bash
make check
```

Runs `pytest -q` and `ruff check .`. Both must be clean — if either breaks,
fix it before committing, don't skip the gate.

## Commit messages

Conventional-commit-style prefix (`feat:`, `fix:`, `docs:`, `chore:`, `test:`)
followed by a short, imperative summary of *why*, not a changelog of every
file touched. See `git log` for the existing style.

## Policy changes

A PR that touches `src/aigis/policy/policy.yaml` (the command allowlist)
must include a test that exercises the change — an allowlist edit with no
test is exactly the kind of silent authority expansion this project's
Policy Engine exists to prevent.

## Scope

Read `CLAUDE.md` and `docs/ARCHITECTURE.md` first. Phase 7 (human approval,
GitHub write access, CI/CD, Credential Broker, RBAC) is explicitly out of
scope until there's a deliberate decision to start it — don't build toward
it incidentally.
