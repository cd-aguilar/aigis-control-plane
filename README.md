# aigis-control-plane

**Evidence-Driven Agent Harness.** A security-first control plane for AI coding
agents that separates agent capability from authorization and task completion.
Agents operate inside ephemeral sandboxes under deny-by-default policies, while
deterministic quality gates and execution evidence — not the LLM — determine
whether a task actually passed.

> Status: Phase 0/1/2/3 done -- domain layer (TaskContract, ToolRequest,
> PolicyDecision, Attempt, TaskState, GateResult, Evidence, Decision,
> AgentClaim) as Pydantic models; Agent Runtime (reducer + provider protocol
> + tool schemas) with a real ClaudeProvider adapter tested via stubs; and a
> Policy Engine (deterministic ALLOW/DENY/REQUIRE_HUMAN) in front of a real
> Sandbox (LocalCowSandbox + a DockerSandbox verified end-to-end against an
> actual Docker daemon: no network, non-root, read-only + tmpfs, resource
> caps). 137 unit tests green, ruff clean. Quality Gates, Evidence Bundle and
> the Decision Engine not implemented yet. See `docs/ARCHITECTURE.md` for the
> full spec, phased roadmap, and current state.
