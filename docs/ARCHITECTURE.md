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

### 16.1 Mapeo a OWASP Top 10 for Agentic Applications (2026)

Correspondencia entre las amenazas de la tabla anterior y el [OWASP Top 10 for
Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
(`ASI01`-`ASI10`, OWASP GenAI Security Project / Agentic Security Initiative).
No es una checklist en verde: el valor de esta tabla está en marcar también lo
que queda **fuera de alcance por diseño** (sección 21), no solo lo cubierto.

| ASI | Nombre | Cobertura en AIGIS | Control(es) relevante(s) | Nota |
|---|---|---|---|---|
| ASI01 | Agent Goal Hijack | ✅ Cubierto | Policy Engine deny-by-default + sandbox (fila "Prompt injection") | Demostrado con evidencia reproducible por S01 (sección 17), no solo documentado. |
| ASI02 | Tool Misuse and Exploitation | ✅ Cubierto | Allowlist de paths (`read_file`/`patch_file`) + allowlist de comandos (`run_command`) — filas "Secret access" y "Unauthorized file modification" | Demostrado end-to-end por S02 (sección 17). |
| ASI03 | Identity and Privilege Abuse | 🟡 Parcial | Least privilege por tool scoping (sección 3.4) | Sin identidad/credencial distinta por agente — el Credential Broker que cerraría esto es Fase 7, explícitamente fuera del alcance inicial (sección 21). |
| ASI04 | Agentic Supply Chain Vulnerabilities | ⬜ Fuera de alcance | — | AIGIS no carga tools ni providers de terceros en runtime: un solo LLM, un solo rol de agente, sin multi-provider (sección 21). Vuelve a ser relevante si el roadmap de la sección 26 avanza. |
| ASI05 | Unexpected Code Execution (RCE) | ✅ Cubierto | Sandbox aislado (`LocalCowSandbox`/`DockerSandbox`) + comandos como argv, nunca shell string — filas "Repo malicioso" y "Command injection" | El diseño de `ToolRequest` (sección 9) rechaza esta clase de ataque por construcción, no la filtra después. |
| ASI06 | Memory and Context Poisoning | ⬜ Fuera de alcance | — | `TaskState` es stateless entre corridas; sin RAG ni memoria persistente (excluido explícitamente, sección 21). |
| ASI07 | Insecure Inter-Agent Communication | ⬜ No aplica | — | Sistema de un solo agente; no hay comunicación inter-agente que asegurar (excluido explícitamente, sección 21). |
| ASI08 | Cascading Failures | ⬜ No aplica todavía | — | Un agente, una tarea por corrida — no hay red de agentes donde una falla se propague. Vuelve a ser relevante si AIGIS pasa a ser infraestructura compartida entre varios tipos de agente (sección 26). |
| ASI09 | Human-Agent Trust Exploitation | 🟡 Parcial | `AgentClaim` nunca lo lee el Decision Engine (sección 8) | Mitiga la sobre-confianza en lo que el agente *dice* que hizo; falta el flujo de aprobación humana en sí — `REQUIRE_HUMAN` decide, pero no hay UI de aprobación todavía (Fase 7). |
| ASI10 | Rogue Agents | 🟡 Parcial | Circuit breaker (`max_iterations`/`max_runtime_seconds`/`max_tool_calls`) + Decision Engine fail-closed — fila "Infinite agent loop" | Contiene un agente que no converge o se desvía dentro de una corrida; no hay monitoreo de comportamiento entre corridas o sesiones. |

Tres filas de la tabla de la sección 16 no tienen un ítem ASI dedicado y
quedan fuera de esta correspondencia 1:1 a propósito: "Network exfiltration"
y "Resource exhaustion" son controles de contención transversales que
sostienen varios ítems ASI a la vez (ASI01, ASI02, ASI05) más que responder a
uno solo; "Evidence tampering" no es una amenaza de comportamiento del
agente sino de integridad del propio control plane — el Top 10 de OWASP
enumera riesgos del agente, no del sistema de auditoría que lo vigila. Es
exactamente lo que motiva evolucionar el Evidence Bundle hacia attestations
firmadas (sección 13).

**Resumen honesto:** de los 10 ítems, 3 están cubiertos con evidencia
reproducible (ASI01, ASI02, ASI05), 3 están parcialmente cubiertos porque el
mecanismo existe pero le falta una pieza ya presente en el roadmap (ASI03,
ASI09, ASI10 — las tres resuelven en Fase 7), y 4 quedan fuera del alcance
actual por diseño, no por descuido (ASI04, ASI06, ASI07, ASI08 — todos
dependen de capacidades que el alcance inicial excluye explícitamente:
multi-provider, RAG/memoria, multi-agente). Esta correspondencia es, en sí
misma, evidencia de que "minimize the blast radius by design" (sección 3.7)
no es una frase vacía: se puede señalar con precisión qué minimiza hoy y qué
todavía no.

---

## 17. Security Evaluation Suite

La seguridad forma parte del sistema de evaluación, no es documentación decorativa.

**Completo (2026-08-29):** S01 — Prompt Injection, S02 — Unauthorized Secret Access, S03 — Path Traversal, S04 — Command Injection, S05 — Resource Exhaustion. Las 5 evals originalmente planeadas están implementadas en `src/aigis/evaluation/security_suite.py`.

Flujo ejemplo (S01-S04): malicious README → agent reads it → agent attempts forbidden action → Policy Engine → DENY → evidence → security evaluation PASS. S05 no encaja en ese flujo — no hay una request que denegar, sino un agente que nunca decide parar por su cuenta; lo que se verifica ahí es que el circuit breaker del contrato (`max_iterations`/`max_tool_calls`/`max_runtime_seconds`, sección 16 "Infinite agent loop") termina el run de forma determinista, sin depender del safety cap absoluto de `AgentRuntime` (que es un backstop, no el mecanismo primario).

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

### Primeros datos reales (2026-08-29): T01-T08 contra `claude-sonnet-5`

Las 8 tareas de benchmark de la sección 18, corridas una vez cada una contra
la API real de Claude (`aigis run examples/tasks/T0N/contract.json
examples/tasks/T0N/repo`), agregadas con
`python scripts/aggregate_metrics.py`:

| Métrica | Valor |
|---|---|
| Success rate | **8/8 = 100%** |
| Iteraciones promedio | 4.9 |
| Tool calls promedio | 4.9 |
| Latencia promedio | 10.6 s |
| Costo total | $0.3044 (8/8 runs con datos de tokens) |
| Cost-to-pass | $0.0381 |
| Policy DENY | 0 |
| Policy REQUIRE_HUMAN | 0 |
| Containment rate | N/D — cero acciones no-ALLOW; no hay nada que contener en un benchmark funcional sin condición adversarial scripteada (para eso está la Security Suite, sección 17) |

| Task | Resultado | Iteraciones | Tool calls | Tokens in | Tokens out |
|---|---|---|---|---|---|
| T01 | PASS | 5 | 5 | 8442 | 622 |
| T02 | PASS | 5 | 5 | 8625 | 621 |
| T03 | PASS | 4 | 4 | 7034 | 526 |
| T04 | PASS | 5 | 5 | 9698 | 682 |
| T05 | PASS | 5 | 5 | 9511 | 703 |
| T06 | PASS | 6 | 6 | 10694 | 2104 |
| T07 | PASS | 4 | 4 | 6855 | 486 |
| T08 | PASS | 5 | 5 | 9216 | 536 |

**Lectura honesta, no un checklist en verde:** N=8, un run cada una — esto
demuestra que el mecanismo funciona con un LLM real de punta a punta, no un
benchmark estadísticamente significativo del agente. T06 (fix regression)
casi triplica el output de cualquier otra tarea; con una sola corrida no se
puede saber si es varianza normal o algo estructural de esa tarea en
particular sin correrla de nuevo. El costo está calculado con la tabla de
precios de `aigis.evaluation.metrics.PRICE_PER_MILLION_TOKENS_USD`
(hardcodeada, se desactualiza si Anthropic cambia el pricing — es una
estimación, no una factura). `T01` de la primera corrida en vivo (27 ago
2026, antes de que existiera el tracking de tokens) quedó fuera de esta
tabla a propósito — no tiene `total_input_tokens`/`total_output_tokens` en
su Evidence Bundle.

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

Refleja la estructura real del repo a partir de Fase 6 (confirmada contra `git ls-files` el 2026-08-27) — no el scaffold aspiracional original de Fase 0. `evals/` y un `sandbox/` a nivel raíz existieron como carpetas vacías (`.gitkeep`) desde el scaffold inicial y nunca se usaron: el código real siempre vivió en `src/aigis/evaluation/` y `src/aigis/sandbox/`; se eliminaron para no confundir a otra sesión con dos carpetas de nombre casi igual. `data/{raw,processed}/` queda como placeholder sin uso — este proyecto no tiene pipeline de datos, no hay ítem del roadmap que lo requiera.

```text
aigis-control-plane/
├── src/aigis/
│   ├── domain/       (task, state, attempt, evidence, decision)
│   ├── agent/        (runtime, reducer, tools)
│   ├── providers/    (claude)
│   ├── policy/       (engine, config, policy.yaml, executor)
│   ├── sandbox/      (base, local_cow, docker_sandbox)
│   ├── evaluation/   (gates, decision_engine, security_suite, benchmark_tasks)
│   ├── evidence/     (bundle)
│   ├── orchestrator.py   (run_task: corre el mecanismo completo de punta a punta)
│   └── cli.py             (`aigis run <contract.json> <repo>`)
├── tests/            (misma forma que src/aigis/, uno a uno)
├── examples/tasks/   (T01/T02/T05 materializadas — ver examples/tasks/README.md)
├── scripts/          (generate_examples.py)
├── docs/             (ARCHITECTURE.md, este documento)
├── data/{raw,processed}/   (placeholder sin uso)
└── CLAUDE.md  README.md  STATUS.md  .gitignore  .env.example  pyproject.toml
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
- **Fase 6 en progreso (2026-08-26/27):** Orquestador end-to-end (`src/aigis/orchestrator.py::run_task`) — corre el mecanismo completo de la sección 1 en una sola llamada: Agent Runtime → Policy Engine/Sandbox → Quality Gates (solo los declarados en `required_gates`) → Evidence Bundle → Decision Engine. CLI real (`src/aigis/cli.py`, `aigis run <contract.json> <repo>`) instalado como entry point de `pyproject.toml`. Se corrigió el model ID desactualizado de `ClaudeProvider` (`claude-sonnet-4-5` → `claude-sonnet-5`). **Corrida real confirmada (27 ago 2026):** `aigis run examples/tasks/T01/contract.json examples/tasks/T01/repo` contra la API real de Claude devolvió `[PASS]` — primera verificación de que el mecanismo completo funciona con un LLM real, no solo con los `ScriptedProvider` deterministas que usan los tests automatizados. Las **8 tareas de la sección 18 completas** (T01-T08; T05 con una condición adversarial — un archivo de secretos fuera de `allowed_paths`/dentro de `forbidden_paths` que nada le pide al agente tocar — y T07 con `config/` en scope en vez de prohibido, a propósito en contraste con T05), materializadas en `examples/tasks/` vía `scripts/generate_examples.py`. Se agregó `.gitattributes` (`* text=auto eol=lf`) para evitar ruido de fin de línea CRLF/LF entre checkouts en Windows.
- **Gap de métricas encontrado y cerrado (2026-08-29):** nada capturaba uso de tokens — la sección 19 pide "token cost"/"cost-to-pass" pero `ClaudeProvider.propose_action` descartaba `response.usage`. Se agregó `ClaudeProvider.usage_summary` (acumulado por instancia) y `total_input_tokens`/`total_output_tokens` opcionales en `EnvironmentMetadata`; `orchestrator.run_task` los lee de forma duck-typed (`getattr(provider, "usage_summary", None)`), así que un `ScriptedProvider` de test no reporta nada en vez de romper. T01 (la única corrida real hasta ahora) es anterior a este fix y no tiene tokens registrados.
- **Fase 6 completa (2026-08-29):** las 8 tareas de benchmark corridas en vivo contra `claude-sonnet-5` real con el tracking de tokens activo — **8/8 PASS**. `src/aigis/evaluation/metrics.py` (`load_run`/`aggregate`) y `scripts/aggregate_metrics.py` agregan success rate, iteraciones/tool calls promedio, latencia, costo y containment rate desde las Evidence Bundles reales — resultados en la sección 19.
- **Fase 5 cerrada del todo (2026-08-29):** S03 (Path Traversal), S04 (Command Injection) y S05 (Resource Exhaustion) implementadas en `security_suite.py`, mismo patrón que S01/S02 — `AgentRuntime` real contra `PolicyEngine`/`LocalCowSandbox` reales, con controles negativos. S05 necesitó una forma distinta (`ResourceExhaustionScenario`/`run_resource_exhaustion_scenario`, un `InfiniteProvider` que nunca llama `ClaimDone`): no hay una request individual que denegar, lo que se verifica es que el circuit breaker del contrato termina el run antes de que haga falta el safety cap absoluto de `AgentRuntime`. Las 5 evals originalmente planeadas en la sección 17 quedan completas.
- Estado de tests verificado el 2026-08-29: **221 tests pasando, 1 skip condicional al entorno**, `ruff check` limpio.

**Pendiente:**
- Fase 7 (Production Hardening) — explícitamente fuera del alcance inicial.
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
