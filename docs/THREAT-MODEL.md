# AIGIS Control Plane — Threat Model

_Desglosado de `ARCHITECTURE.md` sección 16 el 2026-08-29. Ver `ARCHITECTURE.md` para la arquitectura completa y `EVALUATION.md` para cómo se prueba cada control con evidencia reproducible._

## Security Model

> **P0 abierto (desde el 22 sep 2026):** un `run_command` con un ejecutable de la allowlist (`python`) lee rutas prohibidas, escribe fuera de alcance y altera los tests, y la decisión termina en `PASS`. Mientras el P0 siga abierto, varias mitigaciones de esta tabla valen solo para `read_file`/`patch_file`, no para el código que ejecuta un comando permitido. Detalle: `docs/security/P0-review.md`; plan de corrección: `docs/security/P0-design.md`; regresiones: `tests/test_p0_regressions.py`.

| Amenaza | Mitigación | Estado real hoy |
|---|---|---|
| Prompt injection | Policy Engine + sandbox | Bloquea el canal directo (`read_file` → DENY, S01); el canal indirecto vía `run_command` sigue abierto (P0). |
| Repo malicioso | ejecución aislada | Solo en modo docker. El default de `aigis run` es `LocalCowSandbox`, que no aísla el filesystem del host ni la red para el código que ejecuta. |
| Secret access | path policy + ausencia de credenciales sensibles | La path policy cubre `read_file`/`patch_file`; los `forbidden_paths` están físicamente en el workspace y se leen con `run_command` (P0, D2). Las variables de entorno del host sí se filtran. |
| Command injection | argumentos estructurados + allowlist | Argv, nunca shell: vale. La allowlist mira solo `argv[0]` e incluye intérpretes (`python`), así que no restringe qué código corre (P0, D1). |
| Network exfiltration | `--network none` | **Solo en modo docker** (`--sandbox docker`). En modo local (el default) el código ejecutado tiene red. Además, el stdout de un comando vuelve al contexto del LLM: es un canal de salida aunque no haya red. |
| Resource exhaustion | CPU/memory/PID/time limits | CPU/memoria/tiempo en ambos modos; **PIDs solo en docker** (`--pids-limit`): `LocalCowSandbox` no limita procesos desde `838e7bd` (`RLIMIT_NPROC` era por UID, no por sandbox). Los límites POSIX de `LocalCowSandbox` nunca se ejercieron en una corrida real (el benchmark corrió en Windows). |
| Infinite agent loop | iteration/tool/runtime limits | Funciona (S05). |
| Unauthorized file modification | path allowlist | Solo para `patch_file`: una escritura vía `run_command` no queda en `files_changed` y `scope_ok` no la ve (P0, D4). |
| Out-of-band access via allowed command | — (nuevo, P0) | Abierto. Un ejecutable permitido lee o escribe cualquier ruta del workspace. Eval S06 (xfail hasta D1+D2). |
| Grader tampering | `protected_paths` + workspace de evaluación desde la base + reporte fuera del workspace (D3) | **Parcial.** Lo que el agente deja escrito en tests, config de pytest/ruff, `conftest.py` o el reporte no llega al gate, y da FAIL `protected_path_modified` (S07). Sigue abierto: el código del agente corre dentro del proceso del gate (pytest importa `src/`) y puede alterar la corrida desde adentro. Ver `SECURITY.md`. |
| Evidence tampering | checksums SHA-256 en `hashes.json` | **Solo detectan corrupción accidental**: sin clave, sin firma, en el mismo directorio y sin cubrir `decision.json`. Cualquiera con acceso al bundle los recalcula. Receipts firmados: planeado (P3), no implementado. |

La afirmación de seguridad debe ser: **"AIGIS reduces and contains agent risk through layered controls."** Nunca: "AIGIS makes agents secure."

## Mapeo a OWASP Top 10 for Agentic Applications (2026)

Correspondencia entre las amenazas de la tabla anterior y el [OWASP Top 10 for
Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
(`ASI01`-`ASI10`, OWASP GenAI Security Project / Agentic Security Initiative).
No es una checklist en verde: el valor de esta tabla está en marcar también lo
que queda **fuera de alcance por diseño** (ver `ARCHITECTURE.md` sección 21),
no solo lo cubierto.

| ASI | Nombre | Cobertura en AIGIS | Control(es) relevante(s) | Nota |
|---|---|---|---|---|
| ASI01 | Agent Goal Hijack | 🟡 Parcial (era ✅ hasta el 8/11) | Policy Engine deny-by-default + sandbox (fila "Prompt injection") | S01 demuestra el DENY del canal directo (`read_file`). Un agente secuestrado conserva el canal indirecto vía `run_command` (P0). |
| ASI02 | Tool Misuse and Exploitation | 🟡 Parcial (era ✅ hasta el 8/11) | Allowlist de paths (`read_file`/`patch_file`) + allowlist de comandos (`run_command`) — filas "Secret access" y "Unauthorized file modification" | S02/S03 prueban las rutas de `read_file`/`patch_file`. El P0 es exactamente un caso de tool misuse: un tool permitido usado para saltear las reglas de rutas. |
| ASI03 | Identity and Privilege Abuse | 🟡 Parcial | Least privilege por tool scoping (`ARCHITECTURE.md` sección 3.4) | Sin identidad/credencial distinta por agente — el Credential Broker que cerraría esto es Fase 7, explícitamente fuera del alcance inicial. |
| ASI04 | Agentic Supply Chain Vulnerabilities | ⬜ Fuera de alcance | — | AIGIS no carga tools ni providers de terceros en runtime: un solo LLM, un solo rol de agente, sin multi-provider. Vuelve a ser relevante si el roadmap de evolución futura (`ARCHITECTURE.md` sección 26) avanza. |
| ASI05 | Unexpected Code Execution (RCE) | 🟡 Parcial (era ✅ hasta el 8/11) | Sandbox (`LocalCowSandbox`/`DockerSandbox`) + comandos como argv, nunca shell string — filas "Repo malicioso" y "Command injection" | Argv elimina la inyección de shell (S04). Pero ejecutar código es una capacidad permitida (`python`, y `pytest` corre `conftest.py` y tests del repo), y el sandbox por defecto (local) no aísla host ni red. |
| ASI06 | Memory and Context Poisoning | ⬜ Fuera de alcance | — | `TaskState` es stateless entre corridas; sin RAG ni memoria persistente (excluido explícitamente). |
| ASI07 | Insecure Inter-Agent Communication | ⬜ No aplica | — | Sistema de un solo agente; no hay comunicación inter-agente que asegurar (excluido explícitamente). |
| ASI08 | Cascading Failures | ⬜ No aplica todavía | — | Un agente, una tarea por corrida — no hay red de agentes donde una falla se propague. Vuelve a ser relevante si AIGIS pasa a ser infraestructura compartida entre varios tipos de agente. |
| ASI09 | Human-Agent Trust Exploitation | 🟡 Parcial | `AgentClaim` nunca lo lee el Decision Engine | Mitiga la sobre-confianza en lo que el agente *dice* que hizo; falta el flujo de aprobación humana en sí — `REQUIRE_HUMAN` decide, pero no hay UI de aprobación todavía (Fase 7). |
| ASI10 | Rogue Agents | 🟡 Parcial | Circuit breaker (`max_iterations`/`max_runtime_seconds`/`max_tool_calls`) + Decision Engine fail-closed — fila "Infinite agent loop" | Desde el 29/08 tiene evidencia reproducible dedicada: S05 — Resource Exhaustion prueba con un `InfiniteProvider` que el circuit breaker del contrato (no el safety cap absoluto del runtime) es lo que termina un loop sin fin (`EVALUATION.md`). Sigue sin haber monitoreo de comportamiento entre corridas o sesiones — eso seguiría siendo Fase 7. |

Tres filas de la tabla de arriba no tienen un ítem ASI dedicado y quedan
fuera de esta correspondencia 1:1 a propósito: "Network exfiltration" y
"Resource exhaustion" son controles de contención transversales que
sostienen varios ítems ASI a la vez (ASI01, ASI02, ASI05, y desde el 29/08
también ASI10 vía S05) más que responder a uno solo; "Evidence tampering" no
es una amenaza de comportamiento del agente sino de integridad del propio
control plane — el Top 10 de OWASP enumera riesgos del agente, no del
sistema de auditoría que lo vigila. Es exactamente lo que motiva evolucionar
el Evidence Bundle hacia attestations firmadas (`ARCHITECTURE.md` sección 13).

**Resumen honesto (re-evaluado el 8 nov 2026 con el P0 abierto):** de los
10 ítems, **ninguno** queda como cubierto. 6 son parciales: ASI01, ASI02 y
ASI05 bajaron de ✅ a 🟡 por el P0 (los evals S01-S04 siguen pasando, pero
prueban el canal que la policy sí controla, no el que el P0 deja abierto), y
ASI03, ASI09 y ASI10 ya eran parciales porque les falta una pieza de Fase 7.
Los otros 4 quedan
fuera del alcance actual por diseño, no por descuido (ASI04, ASI06, ASI07,
ASI08 — todos dependen de capacidades que el alcance inicial excluye
explícitamente: multi-provider, RAG/memoria, multi-agente). El objetivo de
la tabla es poder señalar con precisión qué controla AIGIS hoy y qué todavía
no. No es una afirmación de conformidad con OWASP.

**Verificación de la fuente (2026-08-27):** la lista ASI01-ASI10 de arriba se
confirmó contra cuatro fuentes independientes (dos artículos de terceros y el
`agent-governance-toolkit` de Microsoft, citado dos veces), después de que
una quinta fuente diera una lista distinta con los mismos códigos ASI0X pero
nombres diferentes — se descartó por discrepar con las otras cuatro.

## AARM — informal gap analysis (8 nov 2026)

[AARM (Autonomous Action Runtime Management)](https://arxiv.org/abs/2602.09433) define 9 requisitos: **Core = R1-R6 (MUST)** y **Extended = R7-R9 (SHOULD)**. La conformidad pública (`aarm.dev`) la revisa y aprueba un grupo de trabajo, con criterios organizacionales que este proyecto no cumple ni busca cumplir. Esto es un **gap analysis informal y conservador**: no afirma conformidad con AARM, ni siquiera parcial. Cada fila se verificó contra el código de `main` del 8/11, con el P0 abierto.

| Req | Nivel | Qué pide (resumen del paper) | AIGIS hoy | Por qué |
|---|---|---|---|---|
| R1 Pre-execution interception | MUST | Interceptar antes de ejecutar y poder bloquear; DENY/DEFER sin efectos; sin modo fail-open; registrar el motivo | 🟡 | `SandboxedToolExecutor` evalúa la policy antes de tocar el sandbox, un DENY no tiene efectos y `events.jsonl` guarda `policy_id` y motivo. Pero un ALLOW de `run_command` tiene efectos que la policy nunca evaluó (P0), y no existe DEFER. |
| R2 Context accumulation | MUST | Acumular contexto de sesión (acciones previas, datos accedidos, pedido original) y dárselo a la policy | ⬜ | `TaskState` acumula los `Attempt`, pero `PolicyEngine.evaluate()` recibe solo la `ToolRequest`: la policy no ve contexto. Sin clasificación de datos. |
| R3 Policy evaluation with intent alignment | MUST | Policy estática + alineación con la intención; validación de parámetros; deferral ante ambigüedad | 🟡 | Policy estática determinista con validación de parámetros (rutas, allowlist, traversal, argv). Sin alineación con la intención ni deferral. |
| R4 Authorization decisions | MUST | ALLOW, DENY, MODIFY, STEP_UP (espera aprobación humana), DEFER | ⬜ | Solo ALLOW/DENY de verdad. `REQUIRE_HUMAN` se parece a STEP_UP pero bloquea la acción (`POLICY_BLOCKED`) sin flujo de aprobación; no hay MODIFY ni DEFER. |
| R5 Tamper-evident receipts | MUST | Receipts **firmados** (Ed25519/ECDSA/RSA) por acción, verificables offline | ⬜ firma / 🟡 registro | Cada acción y decisión queda registrada (`trace.jsonl`, `events.jsonl`, `decision.json`), pero `hashes.json` son checksums sin clave ni firma: no hay tamper-evidence. Una cadena de hashes sin firma ni ancla externa tampoco alcanzaría, porque se puede recalcular entera. |
| R6 Identity binding | MUST | Atar cada acción a principal humano, servicio, agente, sesión y rol | ⬜ | Solo `run_id`/`task_id`. Sin identidades ni validación de credenciales. |
| R7 Semantic distance tracking | SHOULD | Medir la deriva entre la acción y la intención declarada | ⬜ | No implementado. |
| R8 Telemetry export | SHOULD | Exportar telemetría estructurada en tiempo real a un SIEM (OCSF/CEF) | ⬜ | Solo archivos locales en `evidence/`. OpenTelemetry está en Fase 7. |
| R9 Least privilege enforcement | SHOULD | Credenciales just-in-time, con alcance mínimo por acción | 🟡 | Tool scoping por contrato (`allowed_paths`/`forbidden_paths`), env del host filtrada en el sandbox y sin credenciales adentro. Sin credenciales JIT (el Credential Broker es Fase 7), y la allowlist con `python` anula el scoping para comandos (P0). |

**Lectura:** de los 6 requisitos Core, AIGIS cumple parcialmente 2 (R1, R3), en 1 solo registra sin firmar (R5) y 3 no están (R2, R4, R6). De los 3 Extended, R9 es parcial y R7/R8 no están. Fuentes: el paper (arXiv 2602.09433) y `aarm.dev`. No se consultó el protocolo de testing detallado por requisito.
