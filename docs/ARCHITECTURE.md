# AIGIS Control Plane — Arquitectura y Estado Consolidado

> **Evidence-driven security and verification control plane for AI agents.**
>
> El agente puede proponer y ejecutar acciones. **AIGIS determina qué está autorizado, qué ocurrió realmente y si la tarea puede considerarse terminada.**

**Última actualización:** 2026-08-17

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

Esto convierte la autorización en parte de la evidencia.

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

Esto permite cambiar posteriormente la implementación sin modificar el resto del control plane.

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
host_platform
```

Permite comparar posteriormente Model A vs Model B, Prompt v1 vs v2, Agent v1 vs v2, Policy v1 vs v2, sin perder trazabilidad.

---

## 15. Modelo de resultados

Separación entre tres niveles:

- **Execution Outcome**: `COMPLETED / FAILED / TIMEOUT / CANCELLED / POLICY_BLOCKED / RESOURCE_EXCEEDED`
- **Verification Outcome**: `PASS / FAIL / INCONCLUSIVE`
- **Final Decision**: `PASS / FAIL / NEEDS_HUMAN`

Esto permite distinguir correctamente: agente intenta acción prohibida → Policy = DENY → intento registrado → task continúa → tests pasan → security evaluation = PASS. **Una acción bloqueada durante un security evaluation puede ser evidencia de que el control funcionó, no un fallo del sistema.**

---

## 16. Security Model

| Amenaza | Mitigación |
|---|---|
| Prompt injection | Policy Engine + sandbox |
| Repo malicioso | ejecución aislada |
| Secret access | path policy + ausencia de credenciales sensibles |
| Command injection | argumentos estructurados + allowlist |
| Network exfiltration | network disabled |
| Resource exhaustion | CPU/memory/PID/time limits |
| Infinite agent loop | iteration/tool/runtime limits |
| Unauthorized file modification | path allowlist |
| Evidence tampering | post-run artifacts + hashes |

La afirmación de seguridad debe ser: **"AIGIS reduces and contains agent risk through layered controls."** Nunca: "AIGIS makes agents secure."

---

## 17. Security Evaluation Suite

La seguridad forma parte del sistema de evaluación, no es documentación decorativa.

**Inicial**: S01 — Prompt Injection, S02 — Unauthorized Secret Access
**Evolución**: S03 — Path Traversal, S04 — Command Injection, S05 — Resource Exhaustion

Flujo ejemplo: malicious README → agent reads it → agent attempts forbidden action → Policy Engine → DENY → evidence → security evaluation PASS.

La métrica debe hablar de **"containment against the tested attack set"**, nunca de "100% secure".

---

## 18. Evaluation Suite funcional

Conjunto inicial de ocho tareas representativas:

```text
T01 — Fix failing test
T02 — Implement missing function
T03 — Fix edge case
T04 — Refactor function
T05 — Add validation
T06 — Fix regression
T07 — Configuration change
T08 — Documentation/code task
```

Cada task define: initial state, expected behavior, allowed files, forbidden files, expected tests, success criteria, adversarial conditions. La suite prioriza **reproducibilidad y auditabilidad**, no volumen.

---

## 19. Métricas

AIGIS no compite solamente por porcentaje de tareas resueltas.

```text
success rate, average iterations, average tool calls, latency, token cost,
cost-to-pass, policy violations, unauthorized actions, containment rate,
evidence completeness, reproducibility
```

- **Cost-to-pass** = costo total de ejecución / tasks exitosas
- **Containment rate** = acciones no autorizadas bloqueadas / acciones no autorizadas intentadas

Siempre especificando el conjunto de pruebas utilizado.

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

---

## 22. Arquitectura del repositorio

```text
aigis-control-plane/
├── src/aigis/
│   ├── domain/       (task, state, attempt, evidence, decision)
│   ├── agent/        (runtime, reducer, tools)
│   ├── providers/    (base, claude)
│   ├── policy/       (engine, policy.yaml)
│   ├── sandbox/      (docker)
│   ├── evaluation/   (gates, grader, suite/)
│   ├── evidence/     (trace, bundle)
│   └── cli.py
├── tests/  evals/  sandbox/  examples/  docs/
├── data/{raw,processed}/  scripts/
└── CLAUDE.md  README.md  .gitignore  .env.example
```

---

## 23. Dependencias

Base: Python, Pydantic, Pytest, Ruff, Docker, Claude API.

No incorporar inicialmente: LangChain, LangGraph, Chroma, Redis, Postgres, Kafka, Kubernetes. El control flow debe permanecer explícito en código.

---

## 24. Estado actual

**Completado:**
- Arquitectura conceptual y tesis del proyecto consolidadas (este documento).
- Alcance inicial definido.
- `CLAUDE.md` y `README.md` del proyecto escritos.
- Repositorio de GitHub identificado y renombrado a **`cd-aguilar/aigis-control-plane`**; `git init` + primer commit hechos, remoto conectado y con `git push -u origin main` ya realizado (2026-08-25).
- Gestor de dependencias definido (`pyproject.toml`: Pydantic, pytest, pytest-json-report, ruff, pyyaml, anthropic).
- **Fase 0/1 — Core Control Plane (2026-08-24):** domain layer completo como Pydantic models en `src/aigis/domain/` — `TaskContract`, `ToolRequest`, `PolicyDecision`, `Attempt`, `TaskState`, `GateResult`, `Evidence`/`EnvironmentMetadata`, `Decision`. La fórmula del Decision Engine (`contract_valid AND policy_ok AND tests_pass AND lint_pass AND scope_ok AND resource_limits_ok => PASS`) y el rechazo estructural de comandos tipo shell-string en `ToolRequest` ya están enforced por validadores Pydantic.
- **Fase 2 — Agent Execution (2026-08-25):** Agent Runtime como orquestador delgado sobre un reducer sin I/O (`src/aigis/agent/`); `Provider`/`ToolExecutor` como protocolos. `ClaudeProvider` (`src/aigis/providers/claude.py`) arma el prompt, reconstruye la conversación desde `TaskState` (stateless entre llamadas) y parsea la respuesta. Los 3 tools (`read_file`/`patch_file`/`run_command`) tienen su JSON schema y mapean a `ToolRequest`. `AgentClaim` agregado al domain layer — nunca leído por el Decision Engine.
- **Fase 3 — Security Boundary (2026-08-25):** Policy Engine determinista (`src/aigis/policy/`) — ALLOW/DENY/REQUIRE_HUMAN sobre `allowed_paths`/`forbidden_paths` del contrato y un allowlist de comandos en `policy.yaml`, con el mapeo de `risk_level` (CRITICAL deniega todo, HIGH exige humano) wireado. Sandbox (`src/aigis/sandbox/`): `LocalCowSandbox` (copia efímera copy-on-write, límites de recursos POSIX, diff unificado) y `DockerSandbox` (sin red, non-root, filesystem read-only + tmpfs, límites de memoria/CPU/PIDs) — probado contra un daemon Docker real. `SandboxedToolExecutor` conecta ambos como el `ToolExecutor` real que la Fase 2 esperaba.
- **Fase 4 — Evidence & Evaluation (2026-08-26):** Quality Gates ejecutables (`src/aigis/evaluation/gates.py`) — `PytestGate`/`RuffGate` corren dentro del `Sandbox` protocol y se califican desde salida estructurada (`pytest-json-report`, `ruff --output-format json`), nunca regex sobre stdout, per sección 12. Evidence Bundle real (`src/aigis/evidence/bundle.py`): `EvidenceBundleWriter` persiste a disco el layout completo de la sección 13 (`task.json`, `state.json`, `trace.jsonl`, `events.jsonl`, `diff.patch`, `test-report.json`/`lint-report.json`, `environment.json`, `manifest.json`, `hashes.json` con SHA-256 por artefacto), con `decision.json` escrito aparte por no poder autorreferenciar su propio hash. Decision Engine (`src/aigis/evaluation/decision_engine.py`): computa los seis booleanos de la fórmula de la sección 3.2 y resuelve fail-closed (sección 3.6) — `REQUIRE_HUMAN` o un gate requerido sin resultado escalan a `NEEDS_HUMAN`; un `DENY` normal no bloquea un `PASS` legítimo, tal como describe el ejemplo de la sección 15.
- **Fase 5 — Security Evaluation (2026-08-26):** Security Evaluation Suite (`src/aigis/evaluation/security_suite.py`) — S01 (Prompt Injection) y S02 (Unauthorized Secret Access), los dos evals del alcance inicial de la sección 17 (S03-S05 quedan como "Evolución" futura, no en el alcance inicial). Cada escenario corre el `AgentRuntime` real contra un `PolicyEngine`/`LocalCowSandbox` reales (sin mocks), impulsado por un `ScriptedProvider` que reproduce de forma determinista el flujo de la sección 17 ("malicious README → agent reads it → agent attempts forbidden action → Policy Engine → DENY → evidence → security evaluation PASS") sin depender de que un LLM real caiga en la inyección — eso sería no determinista y es una pregunta sobre el modelo, no sobre el sistema; lo que se mide es el contenimiento, consistente con la sección 16 ("AIGIS reduces and contains agent risk", nunca "makes agents secure"). Cada escenario produce un `GateResult` (`GateType.SECURITY`) indistinguible para `EvidenceBundleWriter`/`DecisionEngine` de un gate de pytest/ruff. Incluye controles negativos (contrato permisivo → el harness reporta `passed=False`) que prueban que el arnés puede fallar, no solo que da PASS por casualidad.
- Estado de tests verificado el 2026-08-26: **165 tests pasando, 1 skip condicional al entorno**, `ruff check` limpio.

**Pendiente:**
- Fase 6 — Integration (runs end-to-end, CLI real, benchmark suite, métricas, demo, docs).
- Documentación técnica separada (`SECURITY.md`, `EVALUATION.md`, `THREAT-MODEL.md`) si se decide desglosarlos de este documento.

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
