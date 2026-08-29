# aigis-control-plane — Estado del proyecto

_Última actualización: 29 ago 2026 (docs/DEMO.md agregado — transcript real de las 8 corridas, portfolio-ready)_

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

**Alcance inicial del MVP (sección 21 de `ARCHITECTURE.md`) completo — Fases 0-6.** 221 tests unitarios verdes, 1 skip condicional al entorno, `ruff check` limpio.

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

- **Push pendiente resuelto (29 ago 2026, desde Claude Code nativo):** los 4 commits que habían quedado bloqueados en Cowork (`6dfdc0f`, `db8eaff`, `0457894`, `885b779`) ya están en `origin/main`. Repo público, rama por defecto `main`, remoto al día.
- Se revisó el historial completo de commits buscando claves reales expuestas (`sk-ant-...`, valores de `ANTHROPIC_API_KEY`) — no aparece ninguna. El fixture señuelo de la Fase 5 ya no tiene forma de clave real (ver arriba).
- Sin PRs abiertos, sin ramas obsoletas — todo el trabajo se commitea directo a `main` fase por fase.
- Documentación al día y pusheada: `README.md`, `docs/ARCHITECTURE.md` (spec completa + sección 16.1), `docs/DEMO.md` (transcript real sin editar de las 8 corridas + tabla de métricas, ver hito abajo), `CLAUDE.md` (historial fase por fase + revisión externa), `STATUS.md` (este documento).
- `examples/tasks/` — 8/8 tareas de benchmark materializadas y **corridas en vivo, 8/8 PASS** (`examples/tasks/README.md` tiene las instrucciones para repetirlo).

## Hito: docs/DEMO.md — pieza de portfolio mostrable (29 ago 2026, commit `93affe1`)

Se armó `docs/DEMO.md` con el transcript real y sin editar de `aigis run` contra la API real de Claude para las 8 tareas de benchmark (no un transcript simulado ni reconstruido), más la tabla de métricas agregadas de la sección 19, todo en una sola pieza consultable sin tener que reconstruirla desde `ARCHITECTURE.md`. `README.md` la enlaza junto a `ARCHITECTURE.md`. Esto resuelve parte del punto 4 de "Pendiente" (pulir el portfolio con una demo real).

## Gap encontrado y cerrado antes de correr en vivo: métricas de costo (29 ago 2026)

Antes de gastar tokens reales corriendo las 8 tareas, se detectó que nada capturaba uso de tokens: `ClaudeProvider.propose_action` descartaba `response.usage` de cada llamada, así que "token cost"/"cost-to-pass" (sección 19) iban a quedar vacíos sin importar cuántas tareas se corrieran. Se agregó `ClaudeProvider.usage_summary` (acumulado por instancia) y dos campos opcionales (`total_input_tokens`/`total_output_tokens`) a `EnvironmentMetadata`; `orchestrator.run_task` los lee de forma duck-typed (`getattr(provider, "usage_summary", None)`), así que un `ScriptedProvider` de test simplemente no reporta nada en vez de romper. Probado con un cliente Anthropic stubbeado, sin red. Gracias a esto, las 8 corridas reales de más arriba sí tienen tokens/costo registrados.

## Pendiente

El alcance inicial del MVP está completo. Lo que queda es explícitamente fuera de ese alcance o discrecional, no bloqueante:

1. Fase 7 (Production Hardening): explícitamente fuera del alcance inicial — no adelantar (rechazado en la revisión externa del 27/8, ver arriba).
2. Documentación técnica separada (`SECURITY.md`, `EVALUATION.md`, `THREAT-MODEL.md`) si se decide desglosarla de `ARCHITECTURE.md` — la sección 16.1 nueva es candidata natural para sembrar `THREAT-MODEL.md`. Parte del Día 7 del plan original, todavía no decidido.
3. Opcional: correr T01-T08 una segunda vez para tener más de un dato por tarea — con N=1 por tarea no se puede distinguir varianza normal de algo estructural (ver T06 en la tabla de arriba).
4. Decidir hacia dónde sigue el proyecto ahora que el MVP está cerrado: pulir el portfolio (demo real ya armada en `docs/DEMO.md`; falta mostrar resultados en `aigis-cloud`), o mover el foco a otro de los 5 flagships.

### Incidente de seguridad (27 ago 2026)

Una API key de Anthropic quedó expuesta en texto plano dos veces en una sesión de Claude Code: primero pegada directo en el chat, después visible en una captura de pantalla de PowerShell. Se le indicó a Dario revocarla en `console.anthropic.com` y generar una nueva; quedó un recordatorio programado para el 28 ago a las 9am (hora Argentina) para confirmar que se hizo. Es el segundo incidente de exposición de credenciales del mes — el primero fue un `infisical secrets --env=dev` sin filtrar el 1 ago (documentado en `STATUS.md` de `aigis-cloud`) que volcó 10 secrets en texto plano, incluyendo varias API keys de proveedores LLM. Sin resolver a la fecha de este documento: confirmar que ambas rotaciones se completaron.
