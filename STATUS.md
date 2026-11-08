# aigis-control-plane — Estado del proyecto

_Última actualización: 8 nov 2026 (P0 sigue abierto; fix de portabilidad Linux previo al CI. Antes: 22 sep 2026, P0 de seguridad abierto — bypass de scope vía `run_command`, ver sección dedicada más abajo; reemplaza la anterior de 7 sep)_

Este documento resume el estado real de arquitectura, código y repo para que cualquier sesión o IA (Cowork, Claude Code, ChatGPT, Gemini, o vos) arranque con contexto completo sin tener que re-derivarlo. Subilo al knowledge del Project "Aigis Control Plane" en claude.ai o pegalo directo en el chat de otra IA para consulta cruzada. Para el detalle técnico completo de cada pieza, `docs/ARCHITECTURE.md`; para el historial fase por fase, `CLAUDE.md`.

## Qué es y qué problema resuelve

Control plane de seguridad/autorización/verificación para agentes de IA. Tesis central: *"El agente puede decir que terminó. El sistema decide si es verdad."* Separa tres preguntas que la mayoría de los harnesses de agentes mezclan en una sola respuesta no confiable (la del propio LLM): qué puede hacer el agente (capability), qué está autorizado a hacer ahora mismo (Policy Engine, determinista, externo al LLM) y si la tarea realmente quedó terminada (Decision Engine, calculado desde evidencia verificable — nunca del mensaje del agente).

Primer caso de uso: un coding agent. La arquitectura no está atada a ese caso — ver sección "Evolución futura" de `ARCHITECTURE.md`. Es el proyecto "atípico a propósito" dentro del portfolio de 5 flagships: los otros cuatro (`aigis-detect`, `agent-orchestrator-soc`, `local-rag-second-brain`, `aigis-cloud`) atacan un dominio de seguridad concreto; este es la infraestructura transversal que en teoría podría sostenerlos a todos.

## Estado por fase (roadmap de 8 fases, sin plazos fijos)

| Fase | Qué es | Estado |
|---|---|---|
| 0/1 | Domain layer (Pydantic): TaskContract, ToolRequest, PolicyDecision (ahora con `policy_version` trazable), Attempt, TaskState, GateResult, Evidence, Decision | ✅ completa |
| 2 | Agent Runtime (reducer sin I/O) + ClaudeProvider real | ✅ completa |
| 3 | Policy Engine determinista (ALLOW/DENY/REQUIRE_HUMAN) + Sandbox (LocalCowSandbox + DockerSandbox real, verificado contra un daemon Docker) | ✅ completa |
| 4 | Quality Gates ejecutables (pytest/ruff, salida estructurada) + Evidence Bundle real (hashes SHA-256) + Decision Engine fail-closed | ✅ completa |
| 5 | Security Evaluation Suite — **5/5 evals**: S01 Prompt Injection, S02 Unauthorized Secret Access, S03 Path Traversal, S04 Command Injection, S05 Resource Exhaustion | ✅ completa |
| 6 | Orquestador end-to-end (`run_task`) + CLI real (`aigis run`) + las 8 tareas de benchmark (T01-T08) **corridas en vivo contra `claude-sonnet-5` real: 8/8 PASS** + métricas de la sección 19 agregadas desde datos reales | ✅ completa |
| 7 | Production Hardening (human approval, GitHub write access, CI/CD, Credential Broker, RBAC) | fuera del alcance inicial |

**Alcance inicial del MVP (sección 21 de `ARCHITECTURE.md`) completo — Fases 0-6.** 223 tests unitarios verdes al cierre del MVP (29 ago 2026), 1 skip condicional al entorno, `ruff check` limpio. Conteo real actual (post Dev Container/Makefile, 7 sep 2026, `pytest --collect-only -q`): **234 tests recolectados — 233 verdes, 1 skip condicional al entorno**.

## Hito: Security Evaluation Suite completa (29 ago 2026)

S03 (Path Traversal), S04 (Command Injection) y S05 (Resource Exhaustion) — las 3 que habían quedado como "evolución futura" — ya están en `security_suite.py`, mismo patrón que S01/S02: `AgentRuntime` real contra `PolicyEngine`/`LocalCowSandbox` reales, con controles negativos que prueban que el arnés puede fallar. S05 no encajaba en el molde "una request debe ser DENY" — se agregó `ResourceExhaustionScenario` + un `InfiniteProvider` que nunca llama `ClaimDone`, y lo que se verifica ahí es que el circuit breaker del contrato (no el safety cap absoluto de `AgentRuntime`) es lo que termina un loop sin fin. Con esto, las 5 evals de seguridad originalmente planeadas en la sección 17 quedan completas — 7 tests nuevos, 221 verdes en total.

## Hito: las 8 tareas de benchmark, en vivo, con métricas reales (29 ago 2026)

Dario corrió las 8 tareas contra la API real de Claude desde su propia terminal (nunca compartió la key en el chat):

```
[PASS] T01 .. [PASS] T08 -- 8/8, policy satisfied, all required gates passed, in scope and within limits
```

Se armó `src/aigis/evaluation/metrics.py` (`load_run`/`aggregate`) + `scripts/aggregate_metrics.py` para agregar la sección 19 desde las Evidence Bundles reales, sin necesidad de instrumentar nada nuevo por corrida:

| Métrica | Valor |
|---|---|
| Success rate | **100% (8/8)** |
| Iteraciones / tool calls promedio | 4.9 |
| Latencia promedio | 10.6 s |
| Costo total | $0.3044 |
| Cost-to-pass | $0.0381 |
| Policy DENY / REQUIRE_HUMAN | 0 / 0 |

Tabla completa por tarea y la lectura honesta (N=8, un run cada una, no es benchmark estadísticamente significativo del agente — T06 casi triplicó el output de las demás y no se sabe si es varianza normal) en `docs/ARCHITECTURE.md` sección 19. La primera corrida de T01 (27 ago 2026, `run-f9211fe76909`) es anterior al tracking de tokens y quedó fuera de la tabla de costos a propósito.

## Revisión externa cruzada (27 ago 2026) — tercera ronda

Se recibió una revisión estratégica extensa de otra IA ("Contexto consolidado para evaluación y continuidad"). Evaluación crítica propia + decisión del dueño del proyecto (no aplicado a ciegas):

- **Aceptado y aplicado ya** (costo cero, sin tocar el roadmap de fases):
  - `PolicyDecision.policy_version` — hash SHA-256 (12 hex) de la `PolicyConfig` vigente en el momento de cada decisión, para trazabilidad por-decisión sin tener que cruzar contra `environment.json`. Implementado en `PolicyEngine._hash_policy_config` / `PolicyEngine.__init__` / `PolicyEngine._decision`.
  - Renombrado el fixture señuelo de T05: `STRIPE_SECRET_KEY=sk_live_fake_...` → `AIGIS_TEST_SECRET=fixture_not_a_real_credential` — el valor anterior calzaba con el patrón regex de escáneres de secretos reales (GitHub secret scanning, etc.), lo cual generaba falsos positivos de seguridad sobre un fixture intencional.
  - `.gitattributes` (`* text=auto eol=lf`) — resultó que ya lo había agregado una sesión concurrente (commit `ae80477`) antes de que esta sesión llegara a aplicarlo.
- **Aceptado, no ejecutado todavía** (correcto pero requiere tiempo/decisión propia, no de otra IA): re-priorizar S03-S05 (path traversal, command injection, resource exhaustion) queda a criterio del dueño del proyecto, no una fecha fija.
- **Rechazado por ahora**: adelantar CI/CD, branch protection, CodeQL, Dependabot a esta semana — es scope creep de Fase 7, ya deliberadamente fuera del alcance inicial del MVP.
- **Nota aparte**: la sugerencia de usar este Control Plane como capa compartida para más de un tipo de agente (pentest agent, SOC agent sobre alertas SIEM) es una idea de las IAs consultadas, no un compromiso del dueño del proyecto — se guarda como dirección posible post-MVP, no como tarea.
- Documentado íntegro en `CLAUDE.md` sección "Revisión externa (2026-08-27)" y mirror en el Project doc de claude.ai.

## Mejora de mayor ROI aplicada (27 ago 2026, commit `0457894`)

Se agregó la sección **16.1 "Mapeo a OWASP Top 10 for Agentic Applications (2026)"** en `docs/ARCHITECTURE.md`, a pedido directo del dueño del proyecto (no parte de la revisión externa anterior). Contenido:

- Tabla ASI01-ASI10 completa, verificada contra 4 fuentes independientes convergentes (se descartó 1 fuente en conflicto), con estado de cobertura (✅ cubierto / 🟡 parcial / ⬜ fuera de alcance) y el control concreto de AIGIS que corresponde a cada ítem.
- Resumen honesto: 3 cubiertos, 3 parciales, 4 fuera de alcance — explícitamente no se vende como checklist en verde.
- Nota de verificación de fuente (metodología de cross-check).
- Mirrorado en el Project doc de claude.ai (`claude/aigis-control-plane-architecture.md`).

## Repo GitHub `cd-aguilar/aigis-control-plane`

- **Push del 28/8 resuelto (desde Claude Code nativo):** los 4 commits que habían quedado bloqueados en Cowork (`6dfdc0f`, `db8eaff`, `0457894`, `885b779`) llegaron a `origin/main`. Repo público, rama por defecto `main`.
- **⚠️ 2 commits nuevos sin pushear (29 ago, hechos en esta sesión de Cowork):** `0a82555` (métricas por tarea) y `6bb3d82` (desglose de documentación). Mismo bloqueo estructural que antes — esta sesión no tiene credenciales git para GitHub (`fatal: could not read Username for 'https://github.com'`). Necesitan un `git push origin main` desde Claude Code nativo o manual antes de seguir trabajando, para no divergir del remoto.
- Se revisó el historial completo de commits buscando claves reales expuestas (`sk-ant-...`, valores de `ANTHROPIC_API_KEY`) — no aparece ninguna. El fixture señuelo de la Fase 5 ya no tiene forma de clave real (ver arriba).
- Sin PRs abiertos, sin ramas obsoletas — todo el trabajo se commitea directo a `main` fase por fase.
- Documentación al día localmente, pendiente de push (ver arriba): `README.md`, `docs/ARCHITECTURE.md` (spec, ahora con pointers a los tres documentos desglosados), `docs/THREAT-MODEL.md`, `docs/SECURITY.md`, `docs/EVALUATION.md`, `docs/DEMO.md` (transcript real sin editar de las 8 corridas + tabla de métricas), `CLAUDE.md` (historial fase por fase + revisión externa), `STATUS.md` (este documento).
- `examples/tasks/` — 8/8 tareas de benchmark materializadas y **corridas en vivo, 8/8 PASS** (`examples/tasks/README.md` tiene las instrucciones para repetirlo).

## Hito: docs/DEMO.md — pieza de portfolio mostrable (29 ago 2026, commit `93affe1`)

Se armó `docs/DEMO.md` con el transcript real y sin editar de `aigis run` contra la API real de Claude para las 8 tareas de benchmark (no un transcript simulado ni reconstruido), más la tabla de métricas agregadas de la sección 19, todo en una sola pieza consultable sin tener que reconstruirla desde `ARCHITECTURE.md`. `README.md` la enlaza junto a `ARCHITECTURE.md`. Esto resuelve parte del punto 4 de "Pendiente" (pulir el portfolio con una demo real).

## Hito: documentación desglosada + métricas por tarea (29 ago 2026, commits `0a82555` y `6bb3d82`)

Dos piezas del punto "Pendiente" de más abajo, resueltas en la misma sesión:

- **`aggregate_by_task()`** en `src/aigis/evaluation/metrics.py` + `scripts/aggregate_metrics.py --all --per-task`: `aggregate()` mezclaba todas las tareas en una sola bolsa y no podía distinguir "T06 es estructuralmente más caro" de "esa corrida fue ruido" — la nueva función agrupa por `task_id` y reporta `output_tokens_spread` (min, max) por tarea. Ya corre contra las Evidence Bundles reales existentes: T01-T05 y T07 ya tienen 2-3 corridas acumuladas (spread visible), T06 y T08 siguen en N=1 — T06 es justamente la tarea que la sección 19 marcaba como posible outlier. 2 tests nuevos (223 verdes en total).
- **`docs/ARCHITECTURE.md` desglosado en `docs/THREAT-MODEL.md` (Security Model + mapeo OWASP ASI), `docs/SECURITY.md` (postura y controles: principios, Policy Engine, Sandbox, comandos como argv) y `docs/EVALUATION.md`** (Security Evaluation Suite + benchmark funcional + métricas, con una sección nueva "Segunda pasada (N>1 por tarea) — en curso"). `ARCHITECTURE.md` deja un pointer con el mismo número de sección en cada lugar movido — ninguna referencia cruzada existente se rompió. `README.md` y `CLAUDE.md` enlazan los tres documentos nuevos.

## Gap encontrado y cerrado antes de correr en vivo: métricas de costo (29 ago 2026)

Antes de gastar tokens reales corriendo las 8 tareas, se detectó que nada capturaba uso de tokens: `ClaudeProvider.propose_action` descartaba `response.usage` de cada llamada, así que "token cost"/"cost-to-pass" (sección 19) iban a quedar vacíos sin importar cuántas tareas se corrieran. Se agregó `ClaudeProvider.usage_summary` (acumulado por instancia) y dos campos opcionales (`total_input_tokens`/`total_output_tokens`) a `EnvironmentMetadata`; `orchestrator.run_task` los lee de forma duck-typed (`getattr(provider, "usage_summary", None)`), así que un `ScriptedProvider` de test simplemente no reporta nada en vez de romper. Probado con un cliente Anthropic stubbeado, sin red. Gracias a esto, las 8 corridas reales de más arriba sí tienen tokens/costo registrados.

## Sync con GitHub (2026-09-07)

`origin/main` tenía 1 commit que el local no tenía: `175e718` (LICENSE Apache-2.0, agregado desde GitHub). Sin commits locales sin pushear. Se hizo `git pull` (fast-forward limpio, sin conflictos) tras confirmar con Dario. Baseline reconfirmado post-sync: 223 tests verdes, 1 skip condicional, `ruff check` limpio, 21.87s.

## Hito: Dev Container reproducible (2026-09-07, commit `1ab98cd`)

`.devcontainer/devcontainer.json` (imagen `mcr.microsoft.com/devcontainers/python:3.11`, feature `docker-in-docker:2`, `postCreateCommand` con `pip install -e ".[dev]"` + `docker pull python:3.11-slim`, `ANTHROPIC_API_KEY` vía `remoteEnv`/`localEnv` — nunca hardcodeada) + `.devcontainer/README.md` con la guía de apertura/verificación. Sección "Quickstart with Dev Container" agregada a `README.md` raíz. El extra `dev` de `pyproject.toml` ya existía (pytest, pytest-json-report, ruff) — no hizo falta crearlo. **Sin verificar en esta sesión:** abrir el Dev Container real en VS Code y confirmar que `tests/sandbox/test_docker_sandbox.py::test_run_command_executes_inside_container` corre y pasa adentro (esta sesión no tiene un runtime de VS Code Dev Containers disponible) — queda pendiente que Dario lo abra una vez y confirme.

## Hito: `make demo` — demo de portfolio en un comando (2026-09-07, commit `b8ba159`)

`Makefile` (`setup`, `test`, `lint`, `check`, `demo-task`, `demo-security`, `demo`, `clean-evidence`). `make demo-task` corre `aigis run examples/tasks/T01/...` contra la API real y muestra el `decision.json` del bundle vía el nuevo `scripts/show_last_run.py` (busca el run más nuevo por mtime de `decision.json`). **Decisión de diseño, confirmada con Dario:** `make demo-security` NO corre S01 con `aigis run`/`ClaudeProvider` real — reusa el `ScriptedProvider` determinista existente de `security_suite.py` (mismo mecanismo que los tests) vía el nuevo `scripts/run_security_eval.py`, que escribe un Evidence Bundle real (`security-report.json`/`events.jsonl` con el DENY) usando `EvidenceBundleWriter`. Motivo: `security_suite.py` documenta a propósito que si un LLM real cae o no en la inyección es una pregunta no determinista sobre el modelo, no algo que este suite deba responder — correr S01 contra Claude real podía no reproducir ningún DENY en una corrida dada, rompiendo la garantía de reproducibilidad de este comando. `make demo-security` no necesita `ANTHROPIC_API_KEY`. `make demo` falla en su primera línea (exit 3) si falta la key, antes de tocar red. `make lint` quedó como solo `ruff check .` (no se agregó `ruff format --check .`, ver nota abajo). `pythonpath = ["scripts"]` agregado a `pyproject.toml` para que los tests puedan importar los scripts. 10 tests nuevos (233 verdes, 1 skip condicional, `ruff check` limpio).

**Deuda de formato encontrada, no resuelta en esta sesión (decisión de Dario):** `ruff format --check .` falla hoy en 17 archivos preexistentes (comillas simples vs. dobles) — nunca se había corrido `ruff format` en el repo, solo `ruff check`. Incluye `src/aigis/domain/evidence.py`, `src/aigis/evaluation/decision_engine.py`, varios tests y fixtures generadas en `examples/tasks/` (que salen de `benchmark_tasks.py`). Se decidió no reformatear todo el repo en esta sesión (diff grande, fuera del alcance de la Tarea 2) — `make lint` se quedó en `ruff check .` únicamente, igual que el gate que ya se venía usando en las Fases 0-6.

**Sin verificar en esta sesión:** `make` no está instalado en este host (Windows, Git Bash) — se verificó cada pieza del `Makefile` ejecutando los comandos subyacentes directamente (Python/bash), pero no se corrió `make demo`/`make check` a través del binario `make` en sí. Falta que Dario lo confirme desde su terminal (con `make` instalado, o dentro del Dev Container).

## Hito: higiene de repo (2026-09-07, commit `0b288b2`)

`LICENSE` con el copyright holder completo (`2026 Cesar Dario Aguilar`) — `pyproject.toml` decía `license = "MIT"` mientras el archivo committeado era Apache-2.0, corregido para que coincidan. Discrepancia 221 vs 223 tests resuelta: el número real hoy (`pytest --collect-only -q`) es **234 recolectados, 233 verdes, 1 skip** — README.md/STATUS.md/ARCHITECTURE.md actualizados con el conteo actual, sin reescribir las entradas históricas (223 al cierre del MVP el 29/8 sigue siendo la cifra correcta para ese momento). `CONTRIBUTING.md` agregado (20 líneas: `make check`, convención de commits, regla de test obligatorio para cambios a `policy.yaml`).

**Pendiente para Dario:** actualizar el texto del README del perfil `cd-aguilar/cd-aguilar` (sesión sin acceso a ese repo) — cambiar cualquier mención de "221" o "223 tests" de `aigis-control-plane` por **"234 tests (233 passed, 1 skip)"**.

## P0 en curso: bypass de scope vía `run_command` (22 sep 2026)

**Hallazgo abierto, confirmado contra el código (no contra un documento):** una sesión de Claude Code recibió un brief de P0 que citaba `claude/aigis-control-plane-p0-design-2026-09-22.md` y `claude/aigis-control-plane-security-review-2026-09-22.md` como el diseño completo y el PoC — ninguno de los dos está en el repo. Dario decidió (22/9) seguir igual, reconstruyendo el hallazgo desde `STATUS.md`/`ARCHITECTURE.md`/el código, y preguntando decisión por decisión en vez de esperar los documentos. El hallazgo en sí se confirmó de forma independiente leyendo `policy/engine.py`, `sandbox/local_cow.py`, `domain/task_state.py` y `evaluation/decision_engine.py` — no es una afirmación sin verificar del brief original.

**Mecanismo confirmado:** `PolicyEngine._evaluate_command` (`src/aigis/policy/engine.py`) sólo evalúa CMD-002 (`'..'` literal en algún argumento) y CMD-001 (allowlist de `policy.yaml`) — nunca consulta `allowed_paths`/`forbidden_paths` del contrato, a diferencia de `READ_FILE`/`PATCH_FILE`. `LocalCowSandbox.create()` copia el repo base entero al workspace efímero, así que un `forbidden_path` sigue físicamente presente y legible por cualquier ejecutable de la allowlist (`python`, `pytest`, ...). Además, `TaskState.files_changed` sólo se llena vía `changed_path`, que sólo `PATCH_FILE` (`policy/executor.py::_apply_patch`) setea — una escritura hecha con `run_command` (incluyendo reescribir un test que `PytestGate` va a evaluar después) es invisible para `DecisionEngine.scope_ok`. Resultado end a end: un agente puede leer un secreto prohibido, reescribir el test que falla para forzar un PASS, y la `Decision` final da `PASS` igual — confirmado con un PoC reproducible (ver abajo).

**Principio del fix (Dario, 22/9):** la decisión sólo puede depender de datos que el agente no puede escribir.

**Checklist de aceptación (reconstruido — el §8 original del P0 con los 9 criterios no está disponible; esto es un stand-in explícito hasta que Dario lo pase):**

- [x] Regresión reproducible que confirme el bypass, como test automatizado (no sólo como narrativa) — `xfail(strict=True)`, para que cada commit de fix retire el suyo.
- [ ] `RUN_COMMAND` deja de poder leer contenido de un `forbidden_path`.
- [ ] Una escritura hecha vía `run_command` fuera de `allowed_paths` queda registrada (visible para `scope_ok`), no sólo las hechas vía `PATCH_FILE`.
- [ ] Los Quality Gates (`pytest`/`ruff`) corren contra un workspace que el propio agente no pudo alterar sin que quede registrado — no el mismo workspace de ejecución sin verificar.
- [ ] Un error de infraestructura durante la evaluación no puede degradar silenciosamente a PASS/ALLOW (fail-closed → `NEEDS_HUMAN`).
- [ ] `run_command` deja de aceptar un `executable`/`args` arbitrarios dentro de la allowlist — reemplazado por perfiles (`run_tests`/`run_lint`) sin argumentos libres (D1).
- [ ] Imagen de sandbox hardened, pinneada por digest, Docker como default (D5).
- [ ] `deny_escalation=security` por defecto: un DENY sobre PATH-002 o una ruta sensible con gates en verde → `NEEDS_HUMAN`, no `PASS` (D6).
- [ ] `docs/SECURITY.md`/`THREAT-MODEL.md`/README recortan cualquier afirmación no verificada ("unique", "tamper-proof", "production-ready") mientras el P0 sigue abierto.

**Commit 1 — test(security): add failing regressions for P0 bypass (xfail strict)**
Hash: `9b19879`. 3 tests nuevos (2 en `tests/policy/test_executor.py`, 1 en `tests/test_p0_command_bypass.py` nuevo) que reproducen, contra un `LocalCowSandbox`/`SandboxedToolExecutor`/`run_task` reales (sin mocks): lectura de un `forbidden_path` vía `run_command`, escritura fuera de `allowed_paths` vía `run_command` no registrada en `changed_path`, y el PoC combinado (fuga de secreto + test reescrito) terminando en `Decision.final == PASS`. Los tres quedan `xfail(strict=True)` — cualquiera que empiece a pasar sin que el commit correspondiente retire su marcador rompe la suite a propósito. Tests: 233 passed, 3 xfailed, 1 skip | ruff: clean | CI: n.a. (todavía no existe, ver commit 3 del plan).

**Commit 2a — fix(sandbox): drop per-UID RLIMIT_NPROC from LocalCowSandbox (8 nov 2026)**
Hash: `838e7bd`. Encontrado al simular el CI (commit 3) en un contenedor `python:3.11` Linux antes de crear el workflow: **10 tests fallaban en Linux** (los 8 `test_before_state_is_lint_clean[T0N]`, `test_gates_run_for_real_inside_local_cow_sandbox` y el e2e del orquestador). Causa: `_apply_resource_limits` ponía `RLIMIT_NPROC=64`, que es un límite **por UID** (cuenta todos los procesos/hilos del usuario en el host), no por sandbox — ruff (un hilo por core) moría con EAGAIN. Nunca se había visto porque todo, incluido el benchmark 8/8, se corrió en Windows, donde los límites POSIX no se aplican. Fix (decisión de Dario, 8/11): se quita `RLIMIT_NPROC`; el límite de PIDs real queda en `DockerSandbox` (`--pids-limit`, que D5 hace default). `RLIMIT_CPU`/`RLIMIT_AS` siguen. Regresión nueva POSIX-only (100 hilos vivos a la vez): falla con el código viejo, pasa con el nuevo. `docs/SECURITY.md` corregido. Tests: Windows 233 passed, 3 xfailed, 2 skipped; Linux (contenedor) 234 passed, 3 xfailed, 1 skipped | ruff: clean | CI: n.a. (commit siguiente).

**Commit 3 — ci: minimal pytest + ruff workflow (8 nov 2026)**
Hash: se anota en el commit siguiente. `.github/workflows/ci.yml`: push y PR a `main`, `ubuntu-latest`, Python 3.11, `pip install -e ".[dev]"`, `ruff check .`, `pytest -q`. `permissions: contents: read`, sin secrets, sin llamadas a LLM, sin `ruff format --check` (deuda de formato conocida). Badge en `README.md`. En `ubuntu-latest` hay Docker, así que `test_run_command_executes_inside_container` corre de verdad en CI (en el contenedor local de simulación quedaba como skip). También: `graphify-out/` al `.gitignore` y `.devcontainer/devcontainer-lock.json` commiteado (fija la feature docker-in-docker por digest), ambos aprobados por Dario el 8/11. Tests: igual que el commit 2a | ruff: clean | CI: pendiente del primer push (no se pushea sin pedido).

**Pendiente de Dario:**
- Los dos documentos citados en el brief del P0 (`claude/aigis-control-plane-p0-design-2026-09-22.md`, `claude/aigis-control-plane-security-review-2026-09-22.md`) — si existen en otro lado, pasarlos; si no, el checklist de arriba sigue siendo el reconstruido, no el original.
- La salida del `grep` sobre los bundles locales (P0 §5) antes del commit 7 (`D1`, reemplazar `run_command` por `run_tests`/`run_lint`).
- Confirmación de que las credenciales expuestas el 27/8 (ver "Incidente de seguridad" más abajo) efectivamente se rotaron — seguía sin confirmar a la fecha de la última actualización de este documento antes de hoy.

## Pendiente

El alcance inicial del MVP está completo salvo el P0 de seguridad abierto arriba, que pasa a ser bloqueante para cualquier otra cosa. Lo que sigue es lo que quedaba pendiente antes del P0 — explícitamente fuera de ese alcance o discrecional, no bloqueante:

1. Fase 7 (Production Hardening): explícitamente fuera del alcance inicial — no adelantar (rechazado en la revisión externa del 27/8, ver arriba).
2. ~~Documentación técnica separada~~ — hecho el 29/8, ver hito arriba.
3. Completar la segunda pasada del benchmark: correr **T06 y T08 en vivo** (las dos que siguen en N=1; T06 es el outlier de la tabla de métricas) y, si se quiere más señal, una tercera corrida de las que ya tienen 2 (T01-T05, T07). Necesita la API key real de Dario — se corre desde su propia terminal, no desde Cowork, mismo criterio que las 8 corridas originales. Comando: `aigis run examples/tasks/T0N/contract.json examples/tasks/T0N/repo` por tarea, después `python scripts/aggregate_metrics.py --all --per-task` para leer el resultado agrupado por tarea (ya implementado, ver hito arriba).
4. Decidir hacia dónde sigue el proyecto ahora que el MVP está cerrado: pulir el portfolio (demo real ya armada en `docs/DEMO.md`; falta mostrar resultados en `aigis-cloud`), o mover el foco a otro de los 5 flagships.

### Incidente de seguridad (27 ago 2026)

Una API key de Anthropic quedó expuesta en texto plano dos veces en una sesión de Claude Code: primero pegada directo en el chat, después visible en una captura de pantalla de PowerShell. Se le indicó a Dario revocarla en `console.anthropic.com` y generar una nueva; quedó un recordatorio programado para el 28 ago a las 9am (hora Argentina) para confirmar que se hizo. Es el segundo incidente de exposición de credenciales del mes — el primero fue un `infisical secrets --env=dev` sin filtrar el 1 ago (documentado en `STATUS.md` de `aigis-cloud`) que volcó 10 secrets en texto plano, incluyendo varias API keys de proveedores LLM. Sin resolver a la fecha de este documento: confirmar que ambas rotaciones se completaron.
