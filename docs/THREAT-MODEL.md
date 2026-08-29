# AIGIS Control Plane — Threat Model

_Desglosado de `ARCHITECTURE.md` sección 16 el 2026-08-29. Ver `ARCHITECTURE.md` para la arquitectura completa y `EVALUATION.md` para cómo se prueba cada control con evidencia reproducible._

## Security Model

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

## Mapeo a OWASP Top 10 for Agentic Applications (2026)

Correspondencia entre las amenazas de la tabla anterior y el [OWASP Top 10 for
Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
(`ASI01`-`ASI10`, OWASP GenAI Security Project / Agentic Security Initiative).
No es una checklist en verde: el valor de esta tabla está en marcar también lo
que queda **fuera de alcance por diseño** (ver `ARCHITECTURE.md` sección 21),
no solo lo cubierto.

| ASI | Nombre | Cobertura en AIGIS | Control(es) relevante(s) | Nota |
|---|---|---|---|---|
| ASI01 | Agent Goal Hijack | ✅ Cubierto | Policy Engine deny-by-default + sandbox (fila "Prompt injection") | Demostrado con evidencia reproducible por S01 (`EVALUATION.md`). |
| ASI02 | Tool Misuse and Exploitation | ✅ Cubierto | Allowlist de paths (`read_file`/`patch_file`) + allowlist de comandos (`run_command`) — filas "Secret access" y "Unauthorized file modification" | Demostrado end-to-end por S02 y, desde el 29/08, también por S03 — Path Traversal (`EVALUATION.md`). |
| ASI03 | Identity and Privilege Abuse | 🟡 Parcial | Least privilege por tool scoping (`ARCHITECTURE.md` sección 3.4) | Sin identidad/credencial distinta por agente — el Credential Broker que cerraría esto es Fase 7, explícitamente fuera del alcance inicial. |
| ASI04 | Agentic Supply Chain Vulnerabilities | ⬜ Fuera de alcance | — | AIGIS no carga tools ni providers de terceros en runtime: un solo LLM, un solo rol de agente, sin multi-provider. Vuelve a ser relevante si el roadmap de evolución futura (`ARCHITECTURE.md` sección 26) avanza. |
| ASI05 | Unexpected Code Execution (RCE) | ✅ Cubierto | Sandbox aislado (`LocalCowSandbox`/`DockerSandbox`) + comandos como argv, nunca shell string — filas "Repo malicioso" y "Command injection" | El diseño de `ToolRequest` rechaza esta clase de ataque por construcción; desde el 29/08 también con eval dedicado, S04 — Command Injection (`EVALUATION.md`). |
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

**Resumen honesto:** de los 10 ítems, 3 están cubiertos con evidencia
reproducible (ASI01, ASI02, ASI05 — y ASI10 ahora también tiene un eval
dedicado aunque se mantiene como Parcial, ver nota), 3 están parcialmente
cubiertos porque el mecanismo existe pero le falta una pieza ya presente en
el roadmap (ASI03, ASI09, ASI10 — las tres resuelven en Fase 7), y 4 quedan
fuera del alcance actual por diseño, no por descuido (ASI04, ASI06, ASI07,
ASI08 — todos dependen de capacidades que el alcance inicial excluye
explícitamente: multi-provider, RAG/memoria, multi-agente). Esta
correspondencia es, en sí misma, evidencia de que "minimize the blast radius
by design" no es una frase vacía: se puede señalar con precisión qué
minimiza hoy y qué todavía no.

**Verificación de la fuente (2026-08-27):** la lista ASI01-ASI10 de arriba se
confirmó contra cuatro fuentes independientes (dos artículos de terceros y el
`agent-governance-toolkit` de Microsoft, citado dos veces), después de que
una quinta fuente diera una lista distinta con los mismos códigos ASI0X pero
nombres diferentes — se descartó por discrepar con las otras cuatro.
