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
Estructura de carpetas scaffoldeada (2026-08-17). Repo de GitHub identificado
y renombrado a `cd-aguilar/aigis-control-plane` (antes `ai-agent-mcp-automation`),
vacío — sin `git init`/commit/remoto conectado desde la carpeta local todavía.
Sin código funcional: solo `__init__.py` vacíos y un `cli.py` con
`NotImplementedError`. Sin gestor de dependencias definido. Detalle completo en
`docs/ARCHITECTURE.md` sección "Estado actual".

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
- [ ] Fase 0/1: `TaskContract`, `TaskState`, `Attempt`, `QualityGate`, `Evidence`,
      `Decision` como Pydantic models + tests unitarios en `src/aigis/domain/`
- [ ] Definir gestor de dependencias (`pyproject.toml`)
- [ ] `git init` + primer commit + conectar remoto `cd-aguilar/aigis-control-plane`
