# Contexto del proyecto

## Tesis central
> "The agent can claim it is done. The system decides whether it is true."

El LLM propone y ejecuta cambios; nunca tiene autoridad sobre si la tarea está
terminada. Esa decisión la calcula el sistema a partir de evidencia verificable:

```
CAPABILITY → AUTHORIZATION (Policy Engine) → VERIFICATION
```

Implementa el patrón Evaluator-Optimizer de Anthropic ([Building Effective
Agents](https://www.anthropic.com/engineering/building-effective-agents)) con
evaluadores deterministas en vez de LLM-as-judge, y los principios de
[12-Factor Agents](https://github.com/humanlayer/12-factor-agents).

Documento completo de arquitectura + estado: `docs/ARCHITECTURE.md`.

## Qué es
Control plane de seguridad, autorización, ejecución aislada, evidencia y
verificación para agentes de IA. Empieza con un caso de uso concreto — un
coding agent — pero la arquitectura no está atada a ese caso de uso (ver
sección "Evolución futura" en `docs/ARCHITECTURE.md`). Sin plazo de tiempo
fijo: el alcance se organiza en fases (0 a 7), no en días.

## Stack
- Python (Pydantic para domain models)
- Claude API (único LLM/provider en la primera implementación)
- Docker (sandbox efímero, sin red, non-root, OverlayFS/CoW)
- pytest + pytest-json-report, ruff (salida JSON) — quality gates deterministas
- Sin dependencias de infra pesada (sin K8s, sin vector DB, sin GitHub write access)

## Alcance inicial (qué SÍ se construye completo)
Todo el mecanismo `TaskContract → Sandbox → Quality Gates → Evidence → Decisión`,
incluyendo los dos security evals (prompt injection, secret access) — un solo LLM,
un solo rol de agente (Coder), repo de juguete local, una sola credencial en env var.

## Qué NO construir en el alcance inicial
Multi-agente, multi-provider real, GitHub write access/PRs, deploy autónomo,
ejecución de código arbitrario expuesta públicamente, Credential Broker completo,
RAG/vector DB, Kubernetes, workers distribuidos, UI web compleja, observability
pesado. Pertenecen al roadmap (fases posteriores), no al núcleo inicial.

## Estructura del repo
```
aigis-control-plane/
  src/aigis/
    domain/      (task, state, attempt, evidence, decision)
    agent/       (runtime, reducer, tools)
    providers/   (base, claude)
    policy/      (engine, policy.yaml)
    sandbox/     (docker)
    evaluation/  (gates, grader, suite/)
    evidence/    (trace, bundle)
    cli.py
  tests/  evals/  sandbox/  docs/  examples/
```

## Estado actual
Fase 0/1 completa (2026-08-24): domain layer entero como Pydantic models --
`TaskContract`, `ToolRequest`, `PolicyDecision`, `Attempt`, `TaskState`,
`GateResult`, `Evidence`/`EnvironmentMetadata`, `Decision` -- en
`src/aigis/domain/`, con 47 tests unitarios (100% verde) y `ruff check` limpio.
La fórmula del Decision Engine (`contract_valid AND policy_ok AND tests_pass
AND lint_pass AND scope_ok AND resource_limits_ok => PASS`) y el rechazo
estructural de comandos tipo shell-string en `ToolRequest` ya están
enforced por validadores Pydantic, no solo documentados.
`pyproject.toml` definido (Pydantic, pytest, pytest-json-report, ruff).
`git init` + primer commit hechos localmente; remoto `origin` conectado a
`cd-aguilar/aigis-control-plane` pero sin push todavía.
**Fase 2 completa (2026-08-25):** Agent Runtime como orquestador delgado sobre
un reducer sin I/O (`src/aigis/agent/`) -- `Provider`/`ToolExecutor` son
protocolos (Phase 3 los implementa con Policy Engine + Sandbox sin tocar el
runtime). `ClaudeProvider` (`src/aigis/providers/claude.py`) arma el prompt,
reconstruye la conversacion desde `TaskState` (stateless entre llamadas) y
parsea la respuesta -- probado con stubs, sin red. Los 3 tools
(`read_file`/`patch_file`/`run_command`) tienen su JSON schema y el mapeo a
`ToolRequest` reusa las validaciones ya existentes (inyeccion de shell
sigue rechazada). Se agrego `AgentClaim` al domain layer -- la
"confesion" del agente de que termino queda registrada aparte de los
Attempts, nunca la lee el Decision Engine (Fase 4). 88 tests unitarios
(100% verde), `ruff check` limpio. `anthropic` sumado como dependencia base.
Sin implementar aun: Policy Engine, Sandbox reales, Quality Gates ejecutables,
Evidence Bundle real, Decision Engine, Security Evaluation Suite.
Detalle completo en `docs/ARCHITECTURE.md` sección "Estado actual".

## Decisiones clave
- Circuit breaker desde el contrato: `max_iterations`, `max_runtime_seconds`,
  `max_tool_calls`, `max_files_changed` en `TaskContract` → si se excede, `FAIL
  (Max Iterations Exceeded)` determinista, nunca un loop colgado.
- Edición estructurada (`str_replace`/patch), nunca reescritura de archivo completo.
- Comandos como lista de argumentos (`{"executable": "pytest", "args": [...]}`),
  nunca string de shell — elimina inyección de comandos de raíz.
- Sandbox OverlayFS/CoW: repo base read-only + capa efímera para cambios.
- Tests con salida estructurada (`pytest-json-report`), nunca regex sobre stdout.
- Métrica `cost-to-pass` (costo total de tokens / tasks en PASS) como ROI.
- Los dos security evals (prompt injection, secret access) son ciudadanos de
  primera clase del eval suite, no un anexo — resultado esperado: DENY con
  evidencia reproducible.
- Fail closed: cuando no hay certeza suficiente, DENY o NEEDS_HUMAN — nunca se
  concede autoridad implícita.

## Roadmap por fases (sin plazos)
0. Foundation — domain models, config, tests, CLI skeleton
1. Core Control Plane — TaskContract, TaskState, ToolRequest, PolicyDecision, Decision
2. Agent Execution — Claude adapter, Agent Runtime, reducer, tools, límites
3. Security Boundary — Policy Engine, Sandbox, restricciones de paths/comandos/recursos
4. Evidence & Evaluation — Evidence Bundle, reports, trace, Decision Engine
5. Security Evaluation — prompt injection, secret access, path traversal, command injection, resource exhaustion
6. Integration — runs end-to-end, CLI, benchmark suite, métricas, demo, docs
7. Production Hardening (futuro, fuera del alcance inicial) — human approval, GitHub integration, CI/CD, Credential Broker, OpenTelemetry, policy-as-code, artifact signing, evidence store persistente, RBAC

## Revisión externa (2026-08-23)

Segunda consolidación estratégica recibida de otra IA (la primera fue la de
aigis-detect, 2026-08-17). Puntos aceptados y rechazados, discutidos con
Dario en sesión de Cowork:

- **Aceptado:** el diagnóstico de fondo — el portfolio tiene más
  arquitectura/diseño que software terminado, y este proyecto (Control
  Plane) es el que más se beneficia de pasar de diseño a MVP funcional.
  Prioridad #1 reafirmada.
- **Rechazado:** el recorte de la estrategia de portfolio a "3 flagships"
  (Control Plane, Aigis-Detect, Aigis-Pentest), que degradaba a Agent
  Orchestrator a mero conector y dejaba afuera a Segundo Cerebro RAG y al
  sitio web. Dario reafirmó la estrategia de 5 flagships del 21/8 (ver
  memoria de Claude, área aigis-cloud).
- **Rechazado por ahora:** ampliar el diseño con MCP Security Gateway,
  Credential Broker más completo, capa transversal de evaluación (`aigis-evals/`)
  y OpenTelemetry. Ya estaban contemplados como Fase 7 (futuro, fuera del
  alcance inicial) — se decide explícitamente NO escribir nueva
  documentación/arquitectura sobre esto hasta que Fases 0-1 tengan código
  funcional. Evita repetir el mismo patrón de "diseñar antes de implementar"
  que la propia revisión señala como problema del portfolio.

## Próximos pasos
- [x] Fase 0/1: domain models + tests unitarios en `src/aigis/domain/`
- [x] Definir gestor de dependencias (`pyproject.toml`)
- [x] `git init` + primer commit + conectar remoto `cd-aguilar/aigis-control-plane`
- [x] `git push -u origin main` hecho (2026-08-25)
- [x] Fase 2: Claude adapter + Agent Runtime (reducer sin I/O) + tools que
      emiten `ToolRequest` real contra el domain layer
- [ ] Fase 3: Policy Engine determinista (ALLOW/DENY/REQUIRE_HUMAN sobre
      path allowlist + command allowlist) + Sandbox (Docker, OverlayFS/CoW,
      sin red) implementando el protocolo `ToolExecutor` ya definido en
      `src/aigis/agent/executor.py` -- el runtime no deberia necesitar
      cambios
