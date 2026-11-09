# AIGIS Control Plane — Threat Model

_Desglosado de `ARCHITECTURE.md` sección 16 el 2026-08-29. Ver `ARCHITECTURE.md` para la arquitectura completa y `EVALUATION.md` para cómo se prueba cada control con evidencia reproducible._

## Security Model

> **P0 abierto (desde el 22 sep 2026), con parte del fix hecho:** un `run_command` con un ejecutable de la allowlist (`python`) leía rutas prohibidas, escribía fuera de alcance y alteraba los tests, y la decisión terminaba en `PASS`. Desde D4, D2 y D3 (8-9 nov 2026) ese PoC da FAIL: los prohibidos no están en el workspace, un cambio fuera de `patch_file` se observa y falla, y los insumos de los gates salen de la base. Desde D1 el agente no tiene un tool de comandos genérico (solo `run_tests`/`run_lint`, con perfiles fijos). Sigue abierto que el código que escribe el agente corre dentro de pytest, y que en modo local ve el host, repo base incluido, y la red (D5). Mientras tanto, varias mitigaciones de esta tabla valen para los tools, no para el código del agente que pytest importa. Detalle: `docs/security/P0-review.md`; plan de corrección: `docs/security/P0-design.md`; regresiones: `tests/test_p0_regressions.py`.

| Amenaza | Mitigación | Estado real hoy |
|---|---|---|
| Prompt injection | Policy Engine + sandbox | Bloquea el canal directo (`read_file` → DENY, S01) y, desde D1, el de un comando genérico (S06). Queda el canal indirecto de código escrito en `src/` que corre al importarlo pytest: en modo local ve host y red (D5). Lo que escribe en el workspace hace fallar la corrida (D4). |
| Repo malicioso | ejecución aislada | Solo en modo docker. El default de `aigis run` es `LocalCowSandbox`, que no aísla el filesystem del host ni la red para el código que ejecuta. |
| Secret access | path policy + `forbidden_paths` fuera del workspace (D2) + ausencia de credenciales sensibles | **Parcial.** La path policy cubre `read_file`/`patch_file`, y desde D2 los `forbidden_paths` no se copian al workspace. En modo local (el default), código del agente todavía puede leerlos desde el repo base por su ruta absoluta: antes con `run_command` y, desde D1, con código en `src/` que importa `run_tests` (verificados los dos el 9/11; D5). Las variables de entorno del host sí se filtran. |
| Command injection | argv + perfiles fijos (D1) | Argv, nunca shell: vale. Desde D1 el agente no elige ejecutable ni flags: `run_tests`/`run_lint` corren perfiles fijos, la allowlist genérica de `run_command` está vacía (S04 sigue dando DENY CMD-001) y el `path` de `run_tests` no puede ser un flag. No restringe qué hace el código que pytest importa (D5). |
| Network exfiltration | `--network none` | **Solo en modo docker** (`--sandbox docker`). En modo local (el default) el código ejecutado tiene red. Además, el stdout de un comando vuelve al contexto del LLM: es un canal de salida aunque no haya red. |
| Resource exhaustion | CPU/memory/PID/time limits | CPU/memoria/tiempo en ambos modos; **PIDs solo en docker** (`--pids-limit`): `LocalCowSandbox` no limita procesos desde `838e7bd` (`RLIMIT_NPROC` era por UID, no por sandbox). Los límites POSIX de `LocalCowSandbox` nunca se ejercieron en una corrida real (el benchmark corrió en Windows). |
| Infinite agent loop | iteration/tool/runtime limits | Funciona (S05). |
| Unauthorized file modification | path allowlist + cambios observados (D4) | **Cubierto dentro del workspace.** `patch_file` pasa por la allowlist; cualquier otro cambio del workspace se observa comparándolo con la base y da FAIL `untracked_modification` (S08). No se observa una escritura fuera del workspace, en el host, en modo local (D5). |
| Out-of-band access via allowed command | sin tool genérico (D1) + prohibidos fuera del workspace (D2) | **Parcial.** El canal del PoC (un intérprete por `run_command`) está cerrado: DENY CMD-001 y el archivo ausente del workspace (S06). Queda el canal de código del agente que importa `run_tests`: lo que escribe en el workspace se observa (D4), pero en modo local ve el host y la red (D5). |
| Grader tampering | `protected_paths` + workspace de evaluación desde la base + reporte fuera del workspace (D3) | **Parcial.** Lo que el agente deja escrito en tests, config de pytest/ruff, `conftest.py` o el reporte no llega al gate, y da FAIL `protected_path_modified` (S07). Desde el 6c, un skip/xfail producido por el código bajo prueba da FAIL `gate_outcome_changed`, y un `noqa` en un archivo del agente no silencia a ruff. Sigue abierto: el código del agente corre dentro del proceso del gate (pytest importa `src/`) y puede alterar la corrida desde adentro. Ver `SECURITY.md`. |
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
| ASI01 | Agent Goal Hijack | 🟡 Parcial (era ✅ hasta el 8/11) | Policy Engine deny-by-default + sandbox (fila "Prompt injection") | S01 demuestra el DENY del canal directo (`read_file`) y S06 el del comando genérico. Un agente secuestrado conserva el canal de su propio código, que corre dentro de pytest (P0, D5). |
| ASI02 | Tool Misuse and Exploitation | 🟡 Parcial (era ✅ hasta el 8/11) | Allowlist de paths (`read_file`/`patch_file`/`run_tests`) + perfiles fijos (`run_tests`/`run_lint`, D1) — filas "Secret access" y "Unauthorized file modification" | S02/S03 prueban las rutas de `read_file`/`patch_file`, S06 que no hay comando genérico. El P0 era un caso de tool misuse (un tool permitido usado para saltear las reglas de rutas); el tool ya no existe, pero `patch_file` + `run_tests` siguen ejecutando código del agente (D5). |
| ASI03 | Identity and Privilege Abuse | 🟡 Parcial | Least privilege por tool scoping (`ARCHITECTURE.md` sección 3.4) | Sin identidad/credencial distinta por agente — el Credential Broker que cerraría esto es Fase 7, explícitamente fuera del alcance inicial. |
| ASI04 | Agentic Supply Chain Vulnerabilities | ⬜ Fuera de alcance | — | AIGIS no carga tools ni providers de terceros en runtime: un solo LLM, un solo rol de agente, sin multi-provider. Vuelve a ser relevante si el roadmap de evolución futura (`ARCHITECTURE.md` sección 26) avanza. |
| ASI05 | Unexpected Code Execution (RCE) | 🟡 Parcial (era ✅ hasta el 8/11) | Sandbox (`LocalCowSandbox`/`DockerSandbox`) + comandos como argv, nunca shell string — filas "Repo malicioso" y "Command injection" | Argv elimina la inyección de shell (S04) y, desde D1, el agente no tiene intérprete. Pero pytest importa el código que escribe el agente (en `run_tests` y en el gate), y el sandbox por defecto (local) no aísla host ni red (D5). |
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
| R1 Pre-execution interception | MUST | Interceptar antes de ejecutar y poder bloquear; DENY/DEFER sin efectos; sin modo fail-open; registrar el motivo | 🟡 | `SandboxedToolExecutor` evalúa la policy antes de tocar el sandbox, un DENY no tiene efectos y `events.jsonl` guarda `policy_id` y motivo. Desde D1 los únicos comandos son perfiles fijos, pero el código del agente que importa `run_tests` tiene efectos que la policy no evalúa (P0, D5), y no existe DEFER. |
| R2 Context accumulation | MUST | Acumular contexto de sesión (acciones previas, datos accedidos, pedido original) y dárselo a la policy | ⬜ | `TaskState` acumula los `Attempt`, pero `PolicyEngine.evaluate()` recibe solo la `ToolRequest`: la policy no ve contexto. Sin clasificación de datos. |
| R3 Policy evaluation with intent alignment | MUST | Policy estática + alineación con la intención; validación de parámetros; deferral ante ambigüedad | 🟡 | Policy estática determinista con validación de parámetros (rutas, allowlist, traversal, argv). Sin alineación con la intención ni deferral. |
| R4 Authorization decisions | MUST | ALLOW, DENY, MODIFY, STEP_UP (espera aprobación humana), DEFER | ⬜ | Solo ALLOW/DENY de verdad. `REQUIRE_HUMAN` se parece a STEP_UP pero bloquea la acción (`POLICY_BLOCKED`) sin flujo de aprobación; no hay MODIFY ni DEFER. |
| R5 Tamper-evident receipts | MUST | Receipts **firmados** (Ed25519/ECDSA/RSA) por acción, verificables offline | ⬜ firma / 🟡 registro | Cada acción y decisión queda registrada (`trace.jsonl`, `events.jsonl`, `decision.json`), pero `hashes.json` son checksums sin clave ni firma: no hay tamper-evidence. Una cadena de hashes sin firma ni ancla externa tampoco alcanzaría, porque se puede recalcular entera. |
| R6 Identity binding | MUST | Atar cada acción a principal humano, servicio, agente, sesión y rol | ⬜ | Solo `run_id`/`task_id`. Sin identidades ni validación de credenciales. |
| R7 Semantic distance tracking | SHOULD | Medir la deriva entre la acción y la intención declarada | ⬜ | No implementado. |
| R8 Telemetry export | SHOULD | Exportar telemetría estructurada en tiempo real a un SIEM (OCSF/CEF) | ⬜ | Solo archivos locales en `evidence/`. OpenTelemetry está en Fase 7. |
| R9 Least privilege enforcement | SHOULD | Credenciales just-in-time, con alcance mínimo por acción | 🟡 | Tool scoping por contrato (`allowed_paths`/`forbidden_paths`), env del host filtrada en el sandbox y sin credenciales adentro. Sin credenciales JIT (el Credential Broker es Fase 7). Desde D1 no hay comando genérico, pero el código del agente que corre dentro de pytest no tiene scoping propio (P0, D5). |

**Lectura:** de los 6 requisitos Core, AIGIS cumple parcialmente 2 (R1, R3), en 1 solo registra sin firmar (R5) y 3 no están (R2, R4, R6). De los 3 Extended, R9 es parcial y R7/R8 no están. Fuentes: el paper (arXiv 2602.09433) y `aarm.dev`. No se consultó el protocolo de testing detallado por requisito.
