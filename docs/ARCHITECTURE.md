# AIGIS Control Plane — Arquitectura y Estado Consolidado

> **Evidence-driven security and verification control plane for AI agents.**
>
> El agente puede proponer y ejecutar acciones. **AIGIS determina qué está autorizado, qué ocurrió realmente y si la tarea puede considerarse terminada.**

**Última actualización:** 2026-08-29

---

## 1. Qué es AIGIS Control Plane

**AIGIS Control Plane** es un control plane de seguridad, autorización, ejecución aislada, evidencia y verificación para agentes de inteligencia artificial.

El proyecto comienza con un caso de uso concreto: **agentes de coding capaces de modificar y probar software**. La arquitectura, sin embargo, no está atada a ese caso de uso — es el primer target de implementación, no la definición final del producto (ver sección 26).

La arquitectura separa tres conceptos que normalmente quedan mezclados en los agentes autónomos:

```text
CAPABILITY
¿El agente puede ejecutar esta acción?
        ↓
AUTHORIZATION
¿Está autorizado a ejecutarla?
        ↓
VERIFICATION
¿La tarea realmente quedó terminada?
```

El LLM puede proponer acciones y utilizar herramientas, pero **no posee autoridad para aprobar sus propias acciones ni para declarar que una tarea fue completada**.

### Tesis central

> **The agent can claim it is done. The system decides whether it is true.**

La decisión final se obtiene a partir de evidencia verificable y reglas deterministas:

```text
Task Contract
      ↓
Agent
      ↓
Tool Request
      ↓
Policy Engine
      ↓
Sandbox
      ↓
Execution
      ↓
Evidence
      ↓
Quality Gates
      ↓
Decision Engine
      ↓
PASS / FAIL / NEEDS_HUMAN
```

---

## 2. Problema que resuelve

Los coding agents actuales pueden: leer repositorios, modificar archivos, ejecutar comandos, ejecutar tests, iterar sobre errores, utilizar herramientas externas, operar con distintos grados de autonomía.

El problema no es solamente **qué puede hacer el agente**, sino:

1. qué acciones está autorizado a ejecutar;
2. qué recursos puede tocar;
3. qué ocurre si encuentra instrucciones maliciosas;
4. qué sucede si intenta ejecutar una acción no autorizada;
5. cómo se limita su blast radius;
6. cómo se demuestra posteriormente qué hizo;
7. cómo se determina objetivamente si terminó correctamente.

AIGIS aborda este problema mediante una arquitectura donde **la autoridad reside en el control plane y no en el LLM**.

---

## 3. Principios fundamentales

### 3.1 Agent ≠ Authority

El agente tiene capacidades, pero no autoridad.

```text
Agent
  │ request
  ▼
Policy Engine
  ├── ALLOW
  ├── DENY
  └── REQUIRE_HUMAN
```

### 3.2 Deterministic decision making

El LLM nunca decide "Task completed". La decisión se obtiene mediante evidencia:

```text
contract_valid AND policy_ok AND tests_pass
AND lint_pass AND scope_ok AND resource_limits_ok
```

### 3.3 Deny by default

Las acciones no autorizadas se rechazan. La política no intenta determinar si una acción es "probablemente segura" mediante un LLM. La autorización debe ser explícita, determinista, auditable y reproducible.

### 3.4 Least privilege

El agente recibe solamente las capacidades necesarias para la tarea. Ejemplo: `read_file`, `patch_file`, `run_pytest`, `run_ruff` — no implica `read_any_file`, `run_any_command`, `access_network`, `access_credentials`, `modify_any_path`.

### 3.5 Evidence over claims

El sistema confía en: diff, tests, lint, policy decisions, execution trace, resource usage, environment metadata, security evaluations. No confía en: "el agente dice que terminó".

### 3.6 Fail closed

Cuando el sistema no puede determinar con suficiente confianza si una acción está permitida o si una tarea quedó correctamente completada, evita conceder autoridad implícita. Según el contexto: `DENY` o `NEEDS_HUMAN`.

### 3.7 Minimize blast radius

AIGIS no pretende demostrar seguridad absoluta. Su objetivo es: **minimize the blast radius of autonomous agents through explicit authorization, isolation, resource limits and verifiable evidence.**

---

## 4. Arquitectura conceptual

AIGIS se divide conceptualmente en dos planos.

**Control Plane** (autoridad y lógica de decisión): TaskContract, Policy Engine, Evaluation Engine, Evidence Metadata, Decision Engine, Audit, Human Approval.

**Execution Plane** (acciones ejecutadas): Agent Runtime, Tools, Sandbox, Repository, Commands, Tests.

> **The agent operates in the execution plane. Authority lives in the control plane.**

---

## 5. Arquitectura del sistema

```text
                         ┌─────────────────────┐
                         │    TASK CONTRACT    │
                         │ scope               │
                         │ success criteria    │
                         │ limits              │
                         │ risk level          │
                         └──────────┬──────────┘
                                    ▼
                         ┌─────────────────────┐
                         │    AGENT RUNTIME    │
                         │ Claude Adapter      │
                         │ Stateless Reducer   │
                         └──────────┬──────────┘
                               Tool Request
                                    ▼
                       ┌────────────────────────┐
                       │     POLICY ENGINE      │
                       │ ALLOW / DENY / HUMAN   │
                       └───────────┬────────────┘
                                ALLOW
                                    ▼
                       ┌────────────────────────┐
                       │        SANDBOX         │
                       │ Docker · non-root      │
                       │ no network · limits    │
                       │ ephemeral filesystem   │
                       └───────────┬────────────┘
                                    ▼
                       ┌────────────────────────┐
                       │        EVIDENCE        │
                       │ diff · tests · lint    │
                       │ policy events · trace  │
                       │ environment · hashes   │
                       └───────────┬────────────┘
                                    ▼
                       ┌────────────────────────┐
                       │    EVALUATION ENGINE   │
                       │ contract · policy      │
                       │ tests · lint           │
                       │ scope · resources      │
                       └───────────┬────────────┘
                                    ▼
                  ┌────────────────────────────────┐
                  │        DECISION ENGINE          │
                  │   PASS / FAIL / NEEDS_HUMAN     │
                  └────────────────────────────────┘
```

---

## 6. Componentes

| Componente | Responsabilidad |
|---|---|
| **TaskContract** | Define objetivo, alcance, límites y criterios de éxito |
| **Agent Runtime** | Ejecuta el ciclo del agente |
| **Tool Layer** | Expone capacidades controladas al agente |
| **Policy Engine** | Autoriza o rechaza tool requests |
| **Sandbox** | Aísla la ejecución |
| **Quality Gates** | Ejecuta verificaciones deterministas |
| **Evidence Collector** | Captura resultados y trazabilidad |
| **Evaluation Engine** | Evalúa evidencia contra el contrato |
| **Decision Engine** | Produce PASS / FAIL / NEEDS_HUMAN |
| **Security Evaluation Suite** | Prueba las propiedades de seguridad |

---

## 7. TaskContract

Frontera entre la intención humana y la autonomía del agente. Debe definir como mínimo:

```text
task_id, description, allowed_paths, forbidden_paths, success_criteria,
max_iterations, max_runtime_seconds, max_tool_calls, max_files_changed,
risk_level, required_gates
```

### Risk level

Se incorpora desde el principio aunque inicialmente tenga un uso limitado: `LOW / MEDIUM / HIGH / CRITICAL`. Permite evolucionar posteriormente hacia políticas como:

```text
LOW      → automático
MEDIUM   → automático + evidencia
HIGH     → REQUIRE_HUMAN
CRITICAL → DENY
```

---

## 8. Agent Runtime

Modelo de control explícito. Conceptualmente: `(state, event) → new_state`. El agente se comporta como un **stateless reducer**, mientras el estado de la ejecución se mantiene explícitamente fuera del modelo.

Primer proveedor: Claude API, rol Coder. La arquitectura debe permitir posteriormente otros providers (OpenAI, Gemini, modelos locales, etc.) sin modificar el control plane.

---

## 9. Tools

El agente no obtiene acceso directo al sistema — utiliza herramientas controladas.

- **Lectura**: `read_file`
- **Edición**: `patch_file` / `str_replace` (no se prioriza `write_file` arbitrario)
- **Ejecución**: `run_command`, estructurado como `{"executable": "pytest", "args": ["tests/"]}` — nunca `{"command": "pytest tests/ && rm -rf ..."}`.

Esto elimina una clase importante de command injection por construcción, en lugar de intentar filtrar metacaracteres posteriormente.

---

## 10. Policy Engine

Determinista y externo al LLM: `ToolRequest → Policy Engine → PolicyDecision`. Una decisión debe poder registrar `decision`, `policy_id`, `reason`, `risk`, `timestamp`, `request`. Ejemplo:

```json
{"decision": "DENY", "policy_id": "CMD-001", "reason": "Executable not in allowlist", "risk": "HIGH"}
```

Esto convierte la autorización en parte de la evidencia. Ver `SECURITY.md` para el detalle de implementación (orden de reglas, `policy_version`, allowlist).

---

## 11. Sandbox

Ejecución en entorno aislado: Docker, non-root, network disabled, resource limits, ephemeral filesystem, read-only base repository, execution timeout, PID/process limits.

El objetivo no es afirmar "Docker hace imposible escapar", sino **reducir el blast radius y contener la ejecución del agente**.

Abstracción propuesta:

```python
class Sandbox:
    create()
    execute()
    collect_diff()
    destroy()
```

Esto permite cambiar posteriormente la implementación sin modificar el resto del control plane. Ver `SECURITY.md` para el detalle de las dos implementaciones (`LocalCowSandbox`/`DockerSandbox`).

---

## 12. Quality Gates

Deterministas. Inicialmente: `pytest`, `ruff`. Resultados estructurados (ej. `pytest-json-report`) en vez de depender de regex sobre stdout — evita que un gate supuestamente determinista dependa de interpretar texto libre.

---

## 13. Evidence Bundle

```text
evidence/<run-id>/
    manifest.json  task.json  trace.jsonl  state.json  events.jsonl
    diff.patch  test-report.json  lint-report.json  security-report.json
    environment.json  hashes.json  decision.json
```

`manifest.json` y `hashes.json` permiten verificar la integridad de los artefactos — no se necesita blockchain ni infraestructura distribuida para esto.

---

## 14. Reproducibilidad

`environment.json` debe permitir reconstruir el contexto de una ejecución:

```text
run_id, timestamp, model_provider, model, model_version, prompt_version,
agent_version, task_contract_version, policy_version, git_commit,
sandbox_image, sandbox_image_digest, python_version, dependency_lock_hash,
host_platform, total_input_tokens, total_output_tokens
```

Permite comparar posteriormente Model A vs Model B, Prompt v1 vs v2, Agent v1 vs v2, Policy v1 vs v2, sin perder trazabilidad. `total_input_tokens`/`total_output_tokens` se sumaron el 29/08 — ver `EVALUATION.md` sobre el gap de costo que esto cierra.

---

## 15. Modelo de resultados

Separación entre tres niveles:

- **Execution Outcome**: `COMPLETED / FAILED / TIMEOUT / CANCELLED / POLICY_BLOCKED / RESOURCE_EXCEEDED`
- **Verification Outcome**: `PASS / FAIL / INCONCLUSIVE`
- **Final Decision**: `PASS / FAIL / NEEDS_HUMAN`

Esto permite distinguir correctamente: agente intenta acción prohibida → Policy = DENY → intento registrado → task continúa → tests pasan → security evaluation = PASS. **Una acción bloqueada durante un security evaluation puede ser evidencia de que el control funcionó, no un fallo del sistema.**

---

## 16. Security Model (ver `docs/THREAT-MODEL.md`)

Desglosado a su propio documento el 2026-08-29: la tabla de amenazas/mitigaciones y el mapeo completo a OWASP Top 10 for Agentic Applications 2026 (ASI01-ASI10) viven en **`docs/THREAT-MODEL.md`**.

---

## 17. Security Evaluation Suite (ver `docs/EVALUATION.md`)

Desglosado a su propio documento el 2026-08-29: las 5 security evals (S01-S05, sección "Security Evaluation Suite" completa desde el 29/08) viven en **`docs/EVALUATION.md`**.

---

## 18. Evaluation Suite funcional (ver `docs/EVALUATION.md`)

Desglosado a su propio documento el 2026-08-29: las 8 tareas de benchmark (T01-T08) viven en **`docs/EVALUATION.md`**.

---

## 19. Métricas (ver `docs/EVALUATION.md`)

Desglosado a su propio documento el 2026-08-29: la tabla de métricas agregadas de las 8 corridas reales, y el estado de la segunda pasada (N>1 por tarea) en curso, viven en **`docs/EVALUATION.md`**.

---

## 20. Observabilidad

No se incorpora inicialmente una plataforma de observabilidad pesada, pero el modelo de eventos debe ser compatible conceptualmente con OpenTelemetry:

```text
agent.run · agent.tool_call · policy.decision · sandbox.command
evaluation.gate · decision.final
```

Esto permite introducir observabilidad avanzada más adelante sin rediseñar el modelo de ejecución.

---

## 21. Alcance inicial

El alcance inicial debe demostrar el mecanismo completo: `TaskContract → Agent → Policy → Sandbox → Execution → Evidence → Quality Gates → Decision`.

**Incluido:** un LLM, un agente Coder, Claude API, repositorio local, Docker sandbox, Policy Engine, path allowlist, command allowlist, quality gates, Evidence Bundle, Decision Engine, security evaluations, CLI, tests automatizados.

**Deliberadamente excluido del alcance inicial:** multi-agent, multi-provider real, GitHub write access, PR creation, autonomous deployment, Credential Broker completo, RAG, vector database, Kubernetes, workers distribuidos, UI web compleja, observability stack pesado.

Estas características pertenecen al roadmap, no al núcleo inicial.

**El alcance inicial (Fases 0-6) está completo desde el 2026-08-29**: las 5 security evals, las 8 tareas de benchmark corridas en vivo con PASS y las métricas agregadas (`docs/EVALUATION.md`) cierran exactamente lo que esta sección definía como objetivo. Lo que queda (sección 24, "Pendiente") es explícitamente Fase 7 o trabajo discrecional, no una pieza faltante del alcance original.

---

## 22. Arquitectura del repositorio

Refleja la estructura real del repo (confirmada contra `git ls-files` el 2026-08-29) — no el scaffold aspiracional original de Fase 0. `evals/` y un `sandbox/` a nivel raíz existieron como carpetas vacías (`.gitkeep`) desde el scaffold inicial y nunca se usaron: el código real siempre vivió en `src/aigis/evaluation/` y `src/aigis/sandbox/`; se eliminaron para no confundir a otra sesión con dos carpetas de nombre casi igual. `data/{raw,processed}/` queda como placeholder sin uso — este proyecto no tiene pipeline de datos, no hay ítem del roadmap que lo requiera.

```text
aigis-control-plane/
├── src/aigis/
│   ├── domain/       (task, state, attempt, evidence, decision, agent_claim)
│   ├── agent/        (runtime, reducer, tools, provider, executor)
│   ├── providers/    (claude)
│   ├── policy/       (engine, config, policy.yaml, executor)
│   ├── sandbox/      (base, local_cow, docker_sandbox)
│   ├── evaluation/   (gates, decision_engine, security_suite, benchmark_tasks, metrics)
│   ├── evidence/     (bundle)
│   ├── orchestrator.py   (run_task: corre el mecanismo completo de punta a punta)
│   └── cli.py             (`aigis run <contract.json> <repo>`)
├── tests/            (misma forma que src/aigis/, uno a uno)
├── examples/tasks/   (T01-T08 materializadas, 8/8 — ver examples/tasks/README.md)
├── scripts/          (generate_examples.py, aggregate_metrics.py)
├── docs/             (ARCHITECTURE.md, THREAT-MODEL.md, SECURITY.md, EVALUATION.md, DEMO.md)
├── data/{raw,processed}/   (placeholder sin uso)
└── CLAUDE.md  README.md  STATUS.md  .gitignore  .gitattributes  .env.example  pyproject.toml
```

---

## 23. Dependencias

Base: Python, Pydantic, Pytest, Ruff, Docker, Claude API.

No incorporar inicialmente: LangChain, LangGraph, Chroma, Redis, Postgres, Kafka, Kubernetes. El control flow debe permanecer explícito en código.

---

## 24. Estado actual

**MVP (Fases 0-6) completo desde el 2026-08-29.** 223 tests unitarios verdes, 1 skip condicional al entorno, `ruff check` limpio.

**Completado:**
- Arquitectura conceptual y tesis del proyecto consolidadas (este documento).
- Alcance inicial definido y cerrado (sección 21).
- `CLAUDE.md` y `README.md` del proyecto escritos.
- Repositorio de GitHub identificado y renombrado a **`cd-aguilar/aigis-control-plane`**; `git init` + primer commit hechos, remoto conectado y con `git push -u origin main` ya realizado (2026-08-25).
- Gestor de dependencias definido (`pyproject.toml`: Pydantic, pytest, pytest-json-report, ruff, pyyaml, anthropic).
- **Fase 0/1 — Core Control Plane (2026-08-24):** domain layer completo como Pydantic models en `src/aigis/domain/` — `TaskContract`, `ToolRequest`, `PolicyDecision`, `Attempt`, `TaskState`, `GateResult`, `Evidence`/`EnvironmentMetadata`, `Decision`. La fórmula del Decision Engine y el rechazo estructural de comandos tipo shell-string en `ToolRequest` ya están enforced por validadores Pydantic.
- **Fase 2 — Agent Execution (2026-08-25):** Agent Runtime como orquestador delgado sobre un reducer sin I/O (`src/aigis/agent/`); `Provider`/`ToolExecutor` como protocolos. `ClaudeProvider` (`src/aigis/providers/claude.py`) arma el prompt, reconstruye la conversación desde `TaskState` (stateless entre llamadas) y parsea la respuesta. `AgentClaim` agregado al domain layer — nunca leído por el Decision Engine.
- **Fase 3 — Security Boundary (2026-08-25):** Policy Engine determinista y Sandbox — ver `SECURITY.md`. Probado contra un daemon Docker real.
- **Fase 4 — Evidence & Evaluation (2026-08-26):** Quality Gates ejecutables, Evidence Bundle real, Decision Engine fail-closed.
- **Fase 5 completa (2026-08-26 S01/S02, cerrada del todo 2026-08-29 con S03-S05):** Security Evaluation Suite, 5/5 evals — ver `EVALUATION.md`.
- **Fase 6 en progreso (2026-08-26/27):** Orquestador end-to-end + CLI real. Corrida real confirmada (27 ago, T01 PASS). Las 8 tareas de benchmark materializadas en `examples/tasks/` vía `scripts/generate_examples.py`. `.gitattributes` agregado.
- **Gap de métricas encontrado y cerrado (2026-08-29):** `ClaudeProvider.usage_summary` + `total_input_tokens`/`total_output_tokens` en `EnvironmentMetadata` — ver `EVALUATION.md`.
- **Fase 6 completa (2026-08-29):** las 8 tareas de benchmark corridas en vivo contra `claude-sonnet-5` real con tracking de tokens activo — **8/8 PASS**. `src/aigis/evaluation/metrics.py` + `scripts/aggregate_metrics.py` agregan las métricas de `EVALUATION.md`.
- **`docs/DEMO.md` (2026-08-29, commit `93affe1`):** transcript real y sin editar de las 8 corridas, pieza de portfolio.
- **Herramienta de métricas por tarea (2026-08-29):** `aggregate_by_task()` + `scripts/aggregate_metrics.py --per-task`, para poder leer una segunda pasada del benchmark (N>1 por tarea) sin que el agregado global diluya el resultado — ver `EVALUATION.md`, sección "Segunda pasada".
- **Documentación técnica desglosada (2026-08-29):** `docs/THREAT-MODEL.md`, `docs/SECURITY.md` y `docs/EVALUATION.md` separados de este documento — cada uno cubre su propio recorte (amenazas/OWASP, postura y controles de seguridad, evaluación y métricas) en vez de vivir todo en un solo archivo largo.
- Estado de tests verificado el 2026-08-29 (después de sumar la herramienta de métricas por tarea): **223 tests pasando, 1 skip condicional al entorno**, `ruff check` limpio.

**Pendiente:**
- Fase 7 (Production Hardening) — explícitamente fuera del alcance inicial.
- Completar la segunda pasada del benchmark: correr T06 y T08 en vivo (las dos tareas que siguen en N=1) y, si se quiere más señal, una tercera corrida de las que ya tienen 2 — ver `EVALUATION.md`. Esto necesita la API key real de Dario; se corre desde su propia terminal, no desde una sesión de Cowork (mismo criterio que las 8 primeras corridas, para no exponer la key en ningún chat).

Detalle línea por línea de cada fase completada: `CLAUDE.md`, sección "Estado actual".

---

## 25. Roadmap de implementación

Fases de implementación, sin plazos de tiempo asignados — el orden importa, la duración de cada fase es una decisión operativa, no parte de la identidad del proyecto.

- **Phase 0 — Foundation**: domain models, project configuration, tests, CLI skeleton.
- **Phase 1 — Core Control Plane**: TaskContract, TaskState, ToolRequest, PolicyDecision, Decision model.
- **Phase 2 — Agent Execution**: Claude adapter, Agent Runtime, reducer, tools, iteration limits.
- **Phase 3 — Security Boundary**: Policy Engine, Sandbox, path restrictions, command restrictions, resource limits.
- **Phase 4 — Evidence & Evaluation**: Evidence Bundle, test reports, lint reports, execution trace, environment metadata, integrity hashes, Decision Engine.
- **Phase 5 — Security Evaluation**: prompt injection, secret access, path traversal, command injection, resource exhaustion.
- **Phase 6 — Integration**: end-to-end runs, CLI, benchmark suite, métricas, demo, documentación.
- **Phase 7 — Production Hardening** (futuro, fuera del alcance inicial): human approval, GitHub integration, CI/CD, Credential Broker, OpenTelemetry, policy-as-code, artifact signing, persistent evidence store, RBAC.

**El MVP (Fases 0-6) está completo al 2026-08-29.** Phase 7 queda como la única fase sin empezar, deliberadamente fuera del alcance inicial.

---

## 26. Evolución futura

La arquitectura no queda limitada al coding.

```text
                    AIGIS CONTROL PLANE
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
    Coding Agent       Security Agent      SOC Agent
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                 ┌──────────▼──────────┐
                 │ Authorization       │
                 │ Sandbox             │
                 │ Evidence            │
                 │ Evaluation          │
                 │ Audit               │
                 │ Human Approval      │
                 └─────────────────────┘
```

El coding agent es **el primer implementation target**, no la definición definitiva del producto. Esto conecta con un interés más amplio de Dario en combinar agentes de IA con automatización de seguridad (triage de SIEM, threat detection vía Wazuh) — un "pentest agent" o un "SOC agent" sobre alertas tipo SIEM son direcciones exploratorias para después de tener el Control Plane funcionando, no compromisos actuales.

---

## 27. Posicionamiento final

**Nombre:** AIGIS Control Plane

**Descripción corta:** An evidence-driven security and verification control plane for AI agents.

**Propuesta de valor:** Agents execute. Policies authorize. Evidence verifies. The system decides.

**Tesis:** The agent can claim it is done. The system decides whether it is true.

**Diferenciador:** AIGIS no intenta construir otro agente autónomo. Construye la capa de control que permite ejecutar agentes con capacidades explícitas, autorización determinista, aislamiento, evidencia verificable y decisiones independientes del LLM.

Al retirar el plazo fijo original ("MVP de una semana"), el proyecto pasa de enmarcarse como un ejercicio de tiempo acotado a definirse por su arquitectura: una plataforma de control (Security + Authorization + Evidence + Verification) para agentes autónomos, cuyo primer target de implementación es un coding agent. El calendario de ejecución (fases de la sección 25) queda como decisión operativa, no como parte de la identidad del proyecto. Para el objetivo de portfolio en AI Engineering + AI Security, la narrativa deja de ser "sé llamar a una API de LLM" y pasa a ser "sé diseñar controles alrededor de un sistema autónomo no confiable".
