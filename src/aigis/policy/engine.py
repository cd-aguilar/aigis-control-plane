"""PolicyEngine — deterministic ``ToolRequest -> PolicyDecision``.

Per ARCHITECTURE.md section 10: "Determinista y externo al LLM." Nothing in
this module reads a model response or calls an LLM; it only reads the
``TaskContract`` (scope, risk level) and ``PolicyConfig`` (command
allowlist). Given the same request, contract and config, it always returns
the same decision -- that's what makes a PolicyDecision usable as evidence
(section 10: "Esto convierte la autorización en parte de la evidencia.").

Rule order (fail closed, section 3.6 -- the first matching rule wins):

1. ``risk_level`` gate on the *task itself* (section 7's LOW/MEDIUM/HIGH/
   CRITICAL -> automatic/automatic+evidence/REQUIRE_HUMAN/DENY mapping,
   which ``RiskLevel``'s docstring deferred to "the Policy Engine (Phase
   3)" -- this is that wiring): CRITICAL denies every request outright,
   HIGH routes every request to REQUIRE_HUMAN, before path/command rules
   are even consulted.
2. READ_FILE / PATCH_FILE: path traversal and absolute paths are denied
   outright (PATH-001), then ``forbidden_paths`` (PATH-002), then
   ``allowed_paths`` (PATH-003, deny-by-default if nothing matches).
3. RUN_COMMAND: argv path-traversal in any argument (CMD-002), then the
   command allowlist (CMD-001, deny-by-default).

A DENY or REQUIRE_HUMAN here is not a system failure -- per section 15/17,
an agent attempting (and being blocked from) an unauthorized action is
exactly the evidence a security evaluation is looking for.
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

from aigis.domain import PolicyDecision, PolicyDecisionType, RiskLevel, ToolName, ToolRequest
from aigis.domain.task_contract import TaskContract
from aigis.policy.config import PolicyConfig, load_policy_config

_ALLOW = PolicyDecisionType.ALLOW
_DENY = PolicyDecisionType.DENY
_REQUIRE_HUMAN = PolicyDecisionType.REQUIRE_HUMAN


def _is_traversal_or_absolute(path: str) -> bool:
    """True if ``path`` tries to escape the sandboxed repo root.

    Checked here, at the Policy Engine, as well as later inside the Sandbox
    (``local_cow.py``'s realpath check) -- defense in depth, not a
    redundancy bug: the Policy Engine's job is to explain *why* a request
    was denied as auditable evidence; the Sandbox's check is the last line
    of defense if a bug ever let a bad path reach it anyway.
    """
    posix = PurePosixPath(path)
    if posix.is_absolute() or ".." in posix.parts:
        return True
    # A Windows-style absolute path ("C:\\foo") or drive reference must be
    # caught too -- the sandbox may run on either platform (dev sandbox vs.
    # Dario's Windows machine).
    return bool(PureWindowsPath(path).drive)


def _matches_prefix(path: str, prefix: str) -> bool:
    """True if ``path`` is ``prefix`` itself or lives underneath it.

    ``allowed_paths``/``forbidden_paths`` entries are prefixes like
    ``"src/"`` or exact files like ``"README.md"`` -- both are treated as
    PurePosixPath directory/file prefixes, trailing slash optional.
    """
    norm_path = PurePosixPath(path)
    norm_prefix = PurePosixPath(prefix.rstrip("/") or "/")
    return norm_path == norm_prefix or norm_prefix in norm_path.parents


def path_within_scope(path: str, contract: TaskContract) -> bool:
    """True if ``path`` would be ALLOWed by the path-scope rules alone
    (PATH-001..003), independent of the task's ``risk_level``.

    Deliberately reimplements the three checks from ``_evaluate_path``
    instead of calling it or sharing its helpers behind the scenes — this is
    meant to be an *independent* second opinion (the Decision Engine, Phase
    4, uses it against ``TaskState.files_changed`` as a final scope check
    over the whole run), not a code-reuse shortcut. Same defense-in-depth
    reasoning as ``LocalCowSandbox``'s own realpath check: a bug in one
    implementation is far less likely to be mirrored by a second,
    independently-written one.
    """
    if _is_traversal_or_absolute(path):
        return False
    if any(_matches_prefix(path, p) for p in contract.forbidden_paths):
        return False
    return any(_matches_prefix(path, p) for p in contract.allowed_paths)


class PolicyEngine:
    def __init__(self, contract: TaskContract, config: PolicyConfig | None = None) -> None:
        self.contract = contract
        self.config = config or load_policy_config()

    def evaluate(self, request: ToolRequest) -> PolicyDecision:
        risk_decision = self._evaluate_task_risk(request)
        if risk_decision is not None:
            return risk_decision

        if request.tool in (ToolName.READ_FILE, ToolName.PATCH_FILE):
            return self._evaluate_path(request)
        if request.tool == ToolName.RUN_COMMAND:
            return self._evaluate_command(request)
        raise TypeError(f"unhandled tool: {request.tool!r}")  # pragma: no cover

    def _evaluate_task_risk(self, request: ToolRequest) -> PolicyDecision | None:
        if self.contract.risk_level == RiskLevel.CRITICAL:
            return self._decision(
                request,
                _DENY,
                "RISK-001",
                "task risk_level is CRITICAL; all actions are denied",
                RiskLevel.CRITICAL,
            )
        if self.contract.risk_level == RiskLevel.HIGH:
            return self._decision(
                request,
                _REQUIRE_HUMAN,
                "RISK-002",
                "task risk_level is HIGH; requires human approval",
                RiskLevel.HIGH,
            )
        return None

    def _evaluate_path(self, request: ToolRequest) -> PolicyDecision:
        path = request.path
        assert path is not None  # enforced by ToolRequest's own validator

        if _is_traversal_or_absolute(path):
            return self._decision(
                request,
                _DENY,
                "PATH-001",
                f"'{path}' is an absolute path or contains '..' (path traversal)",
                RiskLevel.HIGH,
            )
        forbidden = next(
            (p for p in self.contract.forbidden_paths if _matches_prefix(path, p)), None
        )
        if forbidden is not None:
            return self._decision(
                request,
                _DENY,
                "PATH-002",
                f"'{path}' is inside forbidden path '{forbidden}'",
                RiskLevel.HIGH,
            )
        if not any(_matches_prefix(path, p) for p in self.contract.allowed_paths):
            return self._decision(
                request,
                _DENY,
                "PATH-003",
                f"'{path}' is outside allowed_paths {self.contract.allowed_paths}",
                RiskLevel.HIGH,
            )
        return self._decision(
            request,
            _ALLOW,
            "PATH-000",
            f"'{path}' is within allowed_paths",
            self.contract.risk_level,
        )

    def _evaluate_command(self, request: ToolRequest) -> PolicyDecision:
        executable = request.executable
        assert executable is not None  # enforced by ToolRequest's own validator

        if any(".." in arg for arg in (executable, *request.args)):
            return self._decision(
                request,
                _DENY,
                "CMD-002",
                "argument contains path traversal ('..')",
                RiskLevel.HIGH,
            )
        if executable not in self.config.allowed_commands:
            return self._decision(
                request, _DENY, "CMD-001", "Executable not in allowlist", RiskLevel.HIGH
            )
        return self._decision(
            request,
            _ALLOW,
            "CMD-000",
            f"'{executable}' is in the command allowlist",
            self.contract.risk_level,
        )

    @staticmethod
    def _decision(
        request: ToolRequest,
        decision: PolicyDecisionType,
        policy_id: str,
        reason: str,
        risk: RiskLevel,
    ) -> PolicyDecision:
        return PolicyDecision(
            decision=decision, policy_id=policy_id, reason=reason, risk=risk, request=request
        )
