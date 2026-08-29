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
Desglosado desde el 29/08 en `docs/THREAT-MODEL.md` (amenazas + mapeo
OWASP ASI Top 10 2026), `docs/SECURITY.md` (postura y controles de
seguridad) y `docs/EVALUATION.md` (security evals + benchmark +
métricas) -- `ARCHITECTURE.md` deja pointers en el lugar de cada
sección movida, no rompe ninguna referencia cruzada existente.

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
Estructura real (confirmada contra `git ls-files`, 2026-08-27). Los `evals/`
y `sandbox/` a nivel raíz del scaffold original de Fase 0 eran carpetas
vacías nunca usadas -- se eliminaron para no confundir con
`src/aigis/evaluation/`/`src/aigis/sandbox/`, que sí tienen el código real.
```
aigis-control-plane/
  src/aigis/
    domain/       (task, state, attempt, evidence, decision)
    agent/        (runtime, reducer, tools)
    providers/    (claude)
    policy/       (engine, config, policy.yaml, executor)
    sandbox/      (base, local_cow, docker_sandbox)
    evaluation/   (gates, decision_engine, security_suite, benchmark_tasks, metrics)
    evidence/     (bundle)
    orchestrator.py
    cli.py
  tests/  examples/tasks/  data/{raw,processed}/ (sin uso)
  scripts/  (generate_examples.py, aggregate_metrics.py --per-task)
  docs/     (ARCHITECTURE.md, THREAT-MODEL.md, SECURITY.md, EVALUATION.md, DEMO.md)
  STATUS.md
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
**Fase 3 completa (2026-08-25):** Policy Engine determinista (`src/aigis/policy/`) — ALLOW/DENY/REQUIRE_HUMAN sobre `allowed_paths`/`forbidden_paths` del contrato y un allowlist de comandos en `policy.yaml`; ahora también queda wireado el mapeo de `risk_level` (CRITICAL deniega todo, HIGH exige humano) que había quedado pendiente desde la Fase 0. Sandbox (`src/aigis/sandbox/`): `LocalCowSandbox` (copia efimera tipo copy-on-write, límites de recursos POSIX, diff unificado) y `DockerSandbox` (sin red, non-root, filesystem read-only + tmpfs, límites de memoria/CPU/PIDs) — probado de punta a punta contra un daemon Docker real en esta máquina, no solo con mocks. `SandboxedToolExecutor` conecta ambos como el `ToolExecutor` real que la Fase 2 ya esperaba, sin tocar el runtime. 50 tests nuevos (137 verdes, 1 skip condicional al entorno), `ruff check` limpio.
**Fase 4 completa (2026-08-26):** Quality Gates ejecutables (`src/aigis/evaluation/gates.py`) — `PytestGate` y `RuffGate` corren dentro del `Sandbox` (mismo protocolo que ya usaba `policy/executor.py`) y se califican desde salida estructurada (`pytest-json-report`, `ruff --output-format json`), nunca desde regex sobre stdout. Evidence Bundle real (`src/aigis/evidence/bundle.py`): `EvidenceBundleWriter` escribe a disco `task.json`, `state.json`, `trace.jsonl`, `events.jsonl`, `diff.patch`, `test-report.json`/`lint-report.json`, `environment.json`, `manifest.json` y `hashes.json` (SHA-256 de cada artefacto, JSON con `sort_keys` para reproducibilidad); `decision.json` se escribe aparte una vez que existe el veredicto, ya que no puede autorreferenciar su propio hash. Decision Engine (`src/aigis/evaluation/decision_engine.py`): calcula los seis booleanos de la fórmula (`contract_valid`, `policy_ok`, `tests_pass`, `lint_pass`, `scope_ok`, `resource_limits_ok`) y aplica fail-closed — un `REQUIRE_HUMAN` o un gate requerido faltante escala a `NEEDS_HUMAN` en vez de adivinar; un `DENY` normal, en cambio, no bloquea un `PASS` legítimo (sección 15 de `ARCHITECTURE.md`). `scope_ok` es una segunda verificación independiente (`policy.path_within_scope`, reimplementada aparte del Policy Engine a propósito, no reusada) sobre `TaskState.files_changed`. 21 tests nuevos (158 verdes, 1 skip condicional al entorno), `ruff check` limpio.
**Fase 5 completa (2026-08-26):** Security Evaluation Suite (`src/aigis/evaluation/security_suite.py`) — S01 (Prompt Injection) y S02 (Unauthorized Secret Access), los dos evals del alcance inicial (S03-S05 quedan como evolución futura). Cada escenario corre el `AgentRuntime` real contra un `PolicyEngine` + `LocalCowSandbox` reales (sin mocks) manejado por un `ScriptedProvider` que reproduce de forma determinista "el agente ya decidió intentar la acción prohibida" — deliberadamente no intenta que un LLM real caiga en la inyección (eso sería no determinista y es una pregunta sobre el modelo, no sobre el sistema); lo que se mide es el contenimiento del Policy Engine, no el juicio del LLM. Cada escenario se califica como un `GateResult` normal (`GateType.SECURITY`), indistinguible para `EvidenceBundleWriter`/`DecisionEngine` de un gate de pytest/ruff — un security eval se persiste en `security-report.json` igual que cualquier otro. Se agregaron controles negativos (contrato permisivo → el harness reporta `passed=False`) para probar que el arnés puede fallar, no solo que da PASS por casualidad. 7 tests nuevos (165 verdes, 1 skip condicional al entorno), `ruff check` limpio.
**Fase 6 en progreso (2026-08-26/27):** Orquestador end-to-end (`src/aigis/orchestrator.py::run_task`) — la primera pieza que corre el mecanismo completo de punta a punta: Agent Runtime → Policy Engine/Sandbox → Quality Gates (solo los declarados en `required_gates`) → Evidence Bundle → Decision Engine, en una sola llamada. CLI real (`src/aigis/cli.py`, comando `aigis run <contract.json> <repo> [--sandbox local|docker] [--model] [--json]`) instalado como entry point. Se corrigió el model ID desactualizado de `ClaudeProvider` (`claude-sonnet-4-5` → `claude-sonnet-5`) y se le agregó una property pública `.model`. **Confirmado con una corrida real (27 ago 2026):** `aigis run examples/tasks/T01/contract.json examples/tasks/T01/repo` contra la API real de Claude devolvió `[PASS]` — primera prueba de que todo el mecanismo funciona con un LLM real, no solo con los `ScriptedProvider` deterministas de los tests. **Las 8 tareas de benchmark de la sección 18 completas** (`src/aigis/evaluation/benchmark_tasks.py`): T01 fix failing test, T02 implement missing function, T03 fix edge case, T04 refactor (dos funciones duplicadas comparten el mismo bug), T05 add validation (con condición adversarial: archivo de secretos fuera de scope), T06 fix regression (floor division), T07 configuration change (el único donde `config/` está en scope en vez de prohibido, a propósito en contraste con T05), T08 documentation/code task (la implementación no coincide con su propio docstring). Materializadas en `examples/tasks/<id>/` vía `scripts/generate_examples.py` (fuente de verdad en código). Se agregó `.gitattributes` (`* text=auto eol=lf`) para evitar ruido de fin de línea CRLF/LF en Windows. 31 tests nuevos desde Fase 5 (196 verdes, 1 skip condicional al entorno), `ruff check` limpio.
**Post-Fase-6, higiene sobre revisión externa (27 ago 2026, ver sección más abajo):** `PolicyDecision` suma `policy_version` (hash de 12 hex del `PolicyConfig` cargado, estampado por `PolicyEngine` en cada decisión — trazabilidad por decisión individual, no solo a nivel de `environment.json`). El decoy secret de T05 (`config/secrets.env`) dejó de tener forma de clave real de Stripe (`sk_live_...`, patrón que dispara secret scanners) — ahora `AIGIS_TEST_SECRET=fixture_not_a_real_credential`. Sigue en 196 tests verdes, `ruff check` limpio.
**Gap encontrado y cerrado (2026-08-29):** nada capturaba uso de tokens — la sección 19 pide "token cost"/"cost-to-pass" como métricas del run, pero `ClaudeProvider.propose_action` descartaba `response.usage` sin guardarlo en ningún lado. Se agregó `ClaudeProvider.usage_summary` (acumulado por instancia, no compromete el invariante de "stateless entre llamadas" del Provider protocol, que es sobre qué acción proponer, no sobre telemetría) y dos campos opcionales (`total_input_tokens`/`total_output_tokens`) a `EnvironmentMetadata`; `orchestrator.run_task` los lee vía `getattr(provider, "usage_summary", None)` duck-typed, así que un `ScriptedProvider` (Security Suite, tests del propio orquestador) simplemente no reporta nada en vez de romper. Probado con un cliente Anthropic stubbeado, sin red. 8 tests nuevos (204 verdes, 1 skip condicional al entorno), `ruff check` limpio. T01 (la única corrida real hasta ahora) corrió antes de este fix y no tiene tokens registrados en su Evidence Bundle.
**Fase 6 completa (2026-08-29):** Dario corrió las 8 tareas de benchmark en vivo contra `claude-sonnet-5` real (con el tracking de tokens ya activo) — **8/8 PASS**. Se agregó `src/aigis/evaluation/metrics.py` (`load_run`/`aggregate`, computa success rate, iteraciones/tool calls promedio, latencia, costo vía una tabla de precios por modelo, cost-to-pass, containment rate) y `scripts/aggregate_metrics.py` como CLI sobre eso. Resultados agregados en `docs/ARCHITECTURE.md` sección 19: 100% success rate, 4.9 iteraciones/tool calls promedio, 10.6s de latencia promedio, $0.30 de costo total, $0.038 cost-to-pass, cero DENY/REQUIRE_HUMAN (containment rate no aplica — sin condición adversarial scripteada en estas 8 tareas, para eso está la Security Suite). N=8 con un run cada una: demuestra que el mecanismo funciona con un LLM real de punta a punta, no es un benchmark estadísticamente significativo del agente — documentado así explícitamente, no como checklist en verde. 10 tests nuevos (214 verdes, 1 skip condicional al entorno), `ruff check` limpio.
**Fase 5 cerrada del todo (2026-08-29):** S03 (Path Traversal), S04 (Command Injection), S05 (Resource Exhaustion) — las 3 evals que habían quedado como "evolución futura". Mismo patrón que S01/S02: `AgentRuntime` real contra `PolicyEngine`/`LocalCowSandbox` reales, con controles negativos. S05 no encaja en el molde "una request debe ser DENY" (no hay una request individual que denegar) — se agregó `ResourceExhaustionScenario`/`run_resource_exhaustion_scenario` e `InfiniteProvider` (nunca llama `ClaimDone`), que verifica que el circuit breaker del contrato (`max_iterations`/`max_tool_calls`) termina el run antes de necesitar el safety cap absoluto de 1000 iteraciones de `AgentRuntime`. Las 5 security evals de la sección 17 quedan completas. 7 tests nuevos (221 verdes, 1 skip condicional al entorno), `ruff check` limpio.
**Documentación técnica desglosada y herramienta de métricas por tarea (2026-08-29):** `docs/ARCHITECTURE.md` seccion 16 (Security Model + mapeo OWASP), 17 (Security Evaluation Suite), 18 (benchmark) y 19 (métricas) se movieron a `docs/THREAT-MODEL.md`, `docs/SECURITY.md` y `docs/EVALUATION.md` respectivamente -- `ARCHITECTURE.md` deja un pointer con el mismo número de sección en cada lugar movido, ninguna referencia cruzada existente ("ver sección 21", etc.) se rompió. Se agregó `aggregate_by_task()` en `metrics.py` + `scripts/aggregate_metrics.py --per-task`, necesario para que una segunda pasada del benchmark (N>1 por tarea) pueda distinguir "T06 es estructuralmente más caro" de "esa corrida fue ruido" -- `aggregate()` sola mezcla todas las tareas en una bolsa y no puede responder esa pregunta. Ya corre contra las Evidence Bundles reales existentes: T01-T05 y T07 ya tienen 2-3 corridas acumuladas, T06 y T08 siguen en N=1. 2 tests nuevos (223 verdes, 1 skip condicional al entorno), `ruff check` limpio.
Sin implementar aun: Fase 7 (Production Hardening, fuera del alcance inicial).
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
- El Security Model (sección 16 de `ARCHITECTURE.md`) mapea cada amenaza al
  [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
  (ASI01-ASI10, sección 16.1, agregado 27/08) -- marca tanto lo cubierto con
  evidencia (S01/S02) como lo que queda fuera de alcance a propósito
  (ASI04/06/07/08: multi-provider, RAG, multi-agente -- ninguno construido
  todavía), en vez de afirmar cobertura genérica.

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

## Revisión externa (2026-08-27)

Tercera consolidación estratégica recibida de otra IA (primera: aigis-detect
17/8; segunda: esta misma sección más arriba, 23/8) — esta vez sobre el
`STATUS.md` del proyecto ya con Fase 6 en progreso. Puntos aceptados,
diferidos y rechazados, discutidos con Dario en sesión de Cowork:

- **Aceptado, aplicado de inmediato (costo cero, no toca el roadmap de
  fases):** el diagnóstico de que "196 tests verdes" no comunica por sí
  solo qué tan seguro es el sistema — falta declarar qué prueban realmente
  los tests, no solo cuántos hay. `.gitattributes` para el ruido CRLF/LF ya
  se había aplicado en el mismo commit que completó T03-T08 (`ae80477`,
  27/8). En esta ronda se aplicaron además: `PolicyDecision.policy_version`
  (trazabilidad por decisión individual a la allowlist que la produjo, no
  solo vía `environment.json`) y el rename del decoy secret de T05 lejos de
  un patrón de clave real de Stripe (evita falsos positivos de secret
  scanning en un repo que ya tuvo dos incidentes de credenciales este mes).
- **Aceptado, sin ejecutar todavía:** el argumento de que un eval
  adversarial explícito y reproducible (S03-S05) vale más como evidencia de
  seguridad que la cobertura indirecta que ya dan los tests de Policy
  Engine/Sandbox de la Fase 3. La revisión lo propone como prioridad P1;
  Dario no re-prioriza el roadmap todavía — completar el benchmark de Fase
  6 (T02-T08 en vivo, métricas agregadas) sigue primero. Queda anotado como
  candidato fuerte para la próxima decisión de scope, igual que el 23/8 se
  aceptó el diagnóstico de fondo sin reescribir el plan en el momento.
- **Rechazado por ahora:** CI/CD, branch protection, PRs obligatorios,
  CodeQL, Dependabot, y un `PolicyBackend` intercambiable pensado para un
  futuro backend OPA/Rego. La propia revisión externa ya los ubica en Fase
  6.5/7 ("Production Hardening"), que el plan original ya definía como
  fuera del alcance inicial — adelantarlos ahora, en pleno desarrollo en
  solitario, sería repetir el mismo patrón de "proceso antes que código"
  que la revisión del 23/8 señaló como riesgo del portfolio.
- **Sin fricción, ya encuadrado igual en ambas partes:** attestations
  firmadas del Evidence Bundle (Ed25519/Sigstore) como evolución futura del
  formato de la sección 13 de `ARCHITECTURE.md` — la revisión lo marca como
  P4/futuro y el roadmap ya lo tenía ahí; no requiere ninguna decisión
  nueva.
- **Nota aparte, no es un tema del código:** la revisión reafirma que el
  seguimiento del incidente de exposición de la API key de Anthropic (ver
  `STATUS.md`) sigue siendo la única prioridad P0 real — pero es higiene
  operativa de Dario, no algo que este repositorio pueda resolver por sí
  mismo.

## Próximos pasos
- [x] Fase 0/1: domain models + tests unitarios en `src/aigis/domain/`
- [x] Definir gestor de dependencias (`pyproject.toml`)
- [x] `git init` + primer commit + conectar remoto `cd-aguilar/aigis-control-plane`
- [x] `git push -u origin main` hecho (2026-08-25)
- [x] Fase 2: Claude adapter + Agent Runtime (reducer sin I/O) + tools que
      emiten `ToolRequest` real contra el domain layer
- [x] Fase 3: Policy Engine determinista (ALLOW/DENY/REQUIRE_HUMAN sobre
      path allowlist + command allowlist) + Sandbox (LocalCowSandbox +
      DockerSandbox real, verificado contra un daemon Docker en esta
      máquina) implementando `ToolExecutor` sin tocar el runtime
- [x] Fase 4: Quality Gates ejecutables (pytest/ruff dentro del Sandbox,
      calificados desde salida estructurada) + Evidence Bundle real (diff,
      test-report, lint-report, environment.json, hashes) + Decision Engine
      (PASS/FAIL/NEEDS_HUMAN a partir de evidencia, nunca del mensaje del
      agente)
- [x] Fase 5: Security Evaluation Suite — S01 Prompt Injection, S02
      Unauthorized Secret Access, corridos end-to-end contra el Policy
      Engine + Sandbox reales, calificados como GateResult (GateType.SECURITY)
- [x] Fase 6: orquestador end-to-end + CLI real (`aigis run`) + las 8
      tareas de benchmark corridas en vivo contra `claude-sonnet-5` real —
      **8/8 PASS** (29 ago 2026) — + métricas de la sección 19 agregadas
      (`aigis.evaluation.metrics` / `scripts/aggregate_metrics.py`): 100%
      success rate, $0.30 costo total, $0.038 cost-to-pass, N=8 (un run
      cada una, no estadísticamente significativo — documentado como tal)
- [x] S03/S04/S05 (path traversal, command injection, resource
      exhaustion) — Security Evaluation Suite completa, 5/5 evals
- [x] Documentación técnica desglosada: `docs/THREAT-MODEL.md`,
      `docs/SECURITY.md`, `docs/EVALUATION.md` separados de
      `ARCHITECTURE.md` (29 ago 2026)
- [ ] Segunda pasada del benchmark (N>1 por tarea): correr T06 y T08
      en vivo (siguen en N=1; T06 es el outlier de la sección 19) —
      necesita la API key real de Dario, se corre desde su propia
      terminal, no desde Cowork. `scripts/aggregate_metrics.py --all
      --per-task` ya está listo para leer el resultado agrupado.
- [ ] Fase 7 (Production Hardening) — explícitamente fuera del alcance
      inicial, no empezar sin decisión explícita
