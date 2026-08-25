# aigis-control-plane

**Evidence-Driven Agent Harness.** A security-first control plane for AI coding
agents that separates agent capability from authorization and task completion.
Agents operate inside ephemeral sandboxes under deny-by-default policies, while
deterministic quality gates and execution evidence — not the LLM — determine
whether a task actually passed.

> Status: Phase 0/1/2 done -- domain layer (TaskContract, ToolRequest,
> PolicyDecision, Attempt, TaskState, GateResult, Evidence, Decision,
> AgentClaim) as Pydantic models, plus an Agent Runtime (reducer + provider
> protocol + tool schemas) with a real ClaudeProvider adapter tested via
> stubs. 88 unit tests green, ruff clean. Policy Engine, Sandbox and Quality
> Gates not implemented yet. See `docs/ARCHITECTURE.md` for the full spec,
> phased roadmap, and current state.
