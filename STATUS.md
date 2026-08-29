# aigis-control-plane — Estado del proyecto

_Última actualización: 29 ago 2026_

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
| 5 | Security Evaluation Suite — S01 Prompt Injection, S02 Unauthorized Secret Access | ✅ completa (S03-S05 quedan diferidas, no rechazadas — ver Pendiente) |
| 6 | Orquestador end-to-end (`run_task`) + CLI real (`aigis run`) + 8/8 tareas de benchmark materializadas (T01-T08), 1/8 corrida en vivo (T01, PASS) + tracking de tokens/costo listo para la próxima corrida | 🟡 en progreso |
| 7 | Production Hardening (human approval, GitHub write access, CI/CD, Credential Broker, RBAC) | fuera del alcance inicial |

**204 tests unitarios verdes, 1 skip condicional al entorno, `ruff check` limpio.**

## Hito reciente: primera corrida real contra Claude

El 27 ago 2026 se corrió `aigis run examples/tasks/T01/contract.json examples/tasks/T01/repo` contra la API real de Claude (no un provider scripteado de test) y dio:

```
[PASS] T01 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-f9211fe76909/
```

Primera prueba end-to-end de que el mecanismo completo (Agent Runtime → Policy Engine/Sandbox → Quality Gates → Evidence Bundle → Decision Engine) funciona con un LLM real, no solo con los `ScriptedProvider` deterministas que usan los tests automatizados (Security Suite, orquestador). Las 8 tareas de benchmark (T01-T08) ya están materializadas en `examples/tasks/` (generadas con `scripts/generate_examples.py` desde `src/aigis/evaluation/benchmark_tasks.py`), pero solo T01 se corrió en vivo hasta ahora.

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

- **Push pendiente resuelto (29 ago 2026, desde Claude Code nativo):** los 4 commits que habían quedado bloqueados en Cowork (`6dfdc0f`, `db8eaff`, `0457894`, `885b779`) ya están en `origin/main`. Repo público, rama por defecto `main`, remoto al día.
- Se revisó el historial completo de commits buscando claves reales expuestas (`sk-ant-...`, valores de `ANTHROPIC_API_KEY`) — no aparece ninguna. El fixture señuelo de la Fase 5 ya no tiene forma de clave real (ver arriba).
- Sin PRs abiertos, sin ramas obsoletas — todo el trabajo se commitea directo a `main` fase por fase.
- Documentación al día y pusheada: `README.md`, `docs/ARCHITECTURE.md` (spec completa + sección 16.1), `CLAUDE.md` (historial fase por fase + revisión externa), `STATUS.md` (este documento).
- `examples/tasks/` — 8/8 tareas de benchmark materializadas y listas para correr con una API key real (`examples/tasks/README.md` tiene las instrucciones). Solo T01 corrida en vivo.

## Gap encontrado y cerrado: métricas de costo (29 ago 2026)

Antes de gastar más tokens corriendo T02-T08, se detectó que nada capturaba uso de tokens: `ClaudeProvider.propose_action` descartaba `response.usage` de cada llamada, así que "token cost"/"cost-to-pass" (sección 19) iban a quedar vacíos sin importar cuántas tareas se corrieran. Se agregó `ClaudeProvider.usage_summary` (acumulado por instancia) y dos campos opcionales (`total_input_tokens`/`total_output_tokens`) a `EnvironmentMetadata`; `orchestrator.run_task` los lee de forma duck-typed (`getattr(provider, "usage_summary", None)`), así que un `ScriptedProvider` de test simplemente no reporta nada en vez de romper. Probado con un cliente Anthropic stubbeado, sin red — 8 tests nuevos, 204 verdes en total. **T01 (la única corrida real) es anterior a este fix y no tiene tokens registrados** — para tener datos de costo hace falta volver a correrla o aceptar que T01 queda sin ese dato.

## Pendiente

1. Fase 6: correr T01-T08 en vivo contra la API real con el tracking de tokens ya activo (T01 solo tiene el `[PASS]` registrado, no tokens), agregación de métricas (sección 19 de `ARCHITECTURE.md` — success rate, iteraciones promedio, tool calls promedio, latencia, costo, cost-to-pass, violaciones de policy; requiere varias corridas reales para tener datos que agregar).
2. Fase 5: decidir timing de S03 (path traversal), S04 (command injection), S05 (resource exhaustion) — diferidas, no rechazadas; ya cubiertas indirectamente por los tests de Policy Engine/Sandbox de la Fase 3.
3. Fase 7 (Production Hardening): explícitamente fuera del alcance inicial — no adelantar (rechazado en la revisión externa del 27/8, ver arriba).
4. Documentación técnica separada (`SECURITY.md`, `EVALUATION.md`, `THREAT-MODEL.md`) si se decide desglosarla de `ARCHITECTURE.md` — la sección 16.1 nueva es candidata natural para sembrar `THREAT-MODEL.md`. Parte del Día 7 del plan original, todavía no decidido.

### Incidente de seguridad (27 ago 2026)

Una API key de Anthropic quedó expuesta en texto plano dos veces en una sesión de Claude Code: primero pegada directo en el chat, después visible en una captura de pantalla de PowerShell. Se le indicó a Dario revocarla en `console.anthropic.com` y generar una nueva; quedó un recordatorio programado para el 28 ago a las 9am (hora Argentina) para confirmar que se hizo. Es el segundo incidente de exposición de credenciales del mes — el primero fue un `infisical secrets --env=dev` sin filtrar el 1 ago (documentado en `STATUS.md` de `aigis-cloud`) que volcó 10 secrets en texto plano, incluyendo varias API keys de proveedores LLM. Sin resolver a la fecha de este documento: confirmar que ambas rotaciones se completaron.
