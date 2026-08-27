# aigis-control-plane — Estado del proyecto

_Última actualización: 27 ago 2026 (8/8 tareas de benchmark completas)_

Este documento resume el estado real de arquitectura, código y repo para que cualquier sesión o IA (Cowork, Claude Code, ChatGPT, Gemini, o vos) arranque con contexto completo sin tener que re-derivarlo. Subilo al knowledge del Project "Aigis Control Plane" en claude.ai o pegalo directo en el chat de otra IA para consulta cruzada. Para el detalle técnico completo de cada pieza, `docs/ARCHITECTURE.md`; para el historial fase por fase, `CLAUDE.md`.

## Qué es y qué problema resuelve

Control plane de seguridad/autorización/verificación para agentes de IA. Tesis central: *"El agente puede decir que terminó. El sistema decide si es verdad."* Separa tres preguntas que la mayoría de los harnesses de agentes mezclan en una sola respuesta no confiable (la del propio LLM): qué puede hacer el agente (capability), qué está autorizado a hacer ahora mismo (Policy Engine, determinista, externo al LLM) y si la tarea realmente quedó terminada (Decision Engine, calculado desde evidencia verificable — nunca del mensaje del agente).

Primer caso de uso: un coding agent. La arquitectura no está atada a ese caso — ver sección "Evolución futura" de `ARCHITECTURE.md`. Es el proyecto "atípico a propósito" dentro del portfolio de 5 flagships: los otros cuatro (`aigis-detect`, `agent-orchestrator-soc`, `local-rag-second-brain`, `aigis-cloud`) atacan un dominio de seguridad concreto; este es la infraestructura transversal que en teoría podría sostenerlos a todos.

## Estado por fase (roadmap de 8 fases, sin plazos fijos)

| Fase | Qué es | Estado |
|---|---|---|
| 0/1 | Domain layer (Pydantic): TaskContract, ToolRequest, PolicyDecision, Attempt, TaskState, GateResult, Evidence, Decision | ✅ completa |
| 2 | Agent Runtime (reducer sin I/O) + ClaudeProvider real | ✅ completa |
| 3 | Policy Engine determinista (ALLOW/DENY/REQUIRE_HUMAN) + Sandbox (LocalCowSandbox + DockerSandbox real, verificado contra un daemon Docker) | ✅ completa |
| 4 | Quality Gates ejecutables (pytest/ruff, salida estructurada) + Evidence Bundle real (hashes SHA-256) + Decision Engine fail-closed | ✅ completa |
| 5 | Security Evaluation Suite — S01 Prompt Injection, S02 Unauthorized Secret Access | ✅ completa (S03-S05 quedan como evolución futura) |
| 6 | Orquestador end-to-end (`run_task`) + CLI real (`aigis run`) + 8/8 tareas de benchmark; falta correr T02-T08 en vivo y agregar métricas | 🟡 en progreso |
| 7 | Production Hardening (human approval, GitHub write access, CI/CD, Credential Broker, RBAC) | fuera del alcance inicial |

**196 tests unitarios verdes, 1 skip condicional al entorno, `ruff check` limpio.**

## Hito reciente: primera corrida real contra Claude

El 27 ago 2026 se corrió `aigis run examples/tasks/T01/contract.json examples/tasks/T01/repo` contra la API real de Claude (no un provider scripteado de test) y dio:

```
[PASS] T01 -- policy satisfied, all required gates passed, in scope and within limits
evidence: evidence/run-f9211fe76909/
```

Primera prueba end-to-end de que el mecanismo completo (Agent Runtime → Policy Engine/Sandbox → Quality Gates → Evidence Bundle → Decision Engine) funciona con un LLM real, no solo con los `ScriptedProvider` deterministas que usan los tests automatizados (Security Suite, orquestador). Después de esto se completaron las 8/8 tareas de benchmark de la sección 18 (T02-T08 agregadas el mismo día); ninguna de ellas se corrió todavía en vivo, solo T01.

## Limpieza de estructura (27 ago 2026, commit `fe75c05`)

`git ls-files` mostró dos carpetas fantasma del scaffold original de Fase 0: `evals/` y `sandbox/` a nivel raíz, ambas vacías (solo `.gitkeep`) desde el 17 ago, nunca usadas — el código real siempre vivió en `src/aigis/evaluation/` y `src/aigis/sandbox/`. Se eliminaron por ser confusas (nombres casi idénticos a nivel raíz y dentro de `src/`). De paso se corrigió `.env.example`, que seguía con `AIGIS_CLAUDE_MODEL=claude-sonnet-4-5` (el mismo model ID desactualizado que ya se había corregido en `providers/claude.py` en Fase 6, pero no se había propagado a este archivo). `CLAUDE.md` y `ARCHITECTURE.md` sección 22 actualizados para reflejar la estructura real. Sigue en 186 tests verdes, `ruff check` limpio.

## Repo GitHub `cd-aguilar/aigis-control-plane`

- **Verificado dos veces directamente contra la API de GitHub el 27 ago 2026** (no solo con `git log` local): repo **público**, rama por defecto `main`, `HEAD` remoto idéntico al local ambas veces (0 commits de diferencia en cualquier dirección — último SHA verificado: `fe75c05`).
- Se revisó el historial completo de commits buscando claves reales expuestas (`sk-ant-...`, valores de `ANTHROPIC_API_KEY`) — no aparece ninguna. El único "secreto" en el repo es un fixture falso de la Fase 5 (`STRIPE_SECRET_KEY=sk_live_fake_...` en `examples/tasks/T05`, señuelo intencional para el eval de secret access). `.env` está correctamente ignorado por `.gitignore`.
- Sin PRs abiertos, sin ramas obsoletas — todo el trabajo se commitea directo a `main` fase por fase.
- Documentación al día: `README.md` (explica el problema + dónde encaja en el portfolio), `docs/ARCHITECTURE.md` (spec completa, 27 secciones), `CLAUDE.md` (historial fase por fase), `STATUS.md` (este documento).
- `examples/tasks/` — las 8 tareas de benchmark de la sección 18 materializadas y listas para correr con una API key real (`examples/tasks/README.md` tiene las instrucciones y la tabla completa).

### Higiene local (resuelta 27 ago 2026)

Una sesión anterior había detectado 17 archivos marcados como "modified" por ruido de fin de línea CRLF/LF, sin `.gitattributes` que lo normalizara. Se agregó `.gitattributes` (`* text=auto eol=lf`) al repo; el working tree ya no muestra ese ruido.

## Pendiente

- Fase 6: correr T02-T08 en vivo contra la API real (T01 ya confirmado con PASS), agregación de métricas (sección 19 de `ARCHITECTURE.md` — success rate, cost-to-pass, etc.; requiere varias corridas reales para tener datos que agregar).
- Fase 5: S03 (path traversal), S04 (command injection), S05 (resource exhaustion) — evolución futura, ya cubiertos indirectamente por los tests de Policy Engine/Sandbox de la Fase 3.
- Fase 7 (Production Hardening): explícitamente fuera del alcance inicial.
- Documentación técnica separada (`SECURITY.md`, `EVALUATION.md`, `THREAT-MODEL.md`) si se decide desglosarla de `ARCHITECTURE.md` — parte del Día 7 del plan original.

### Incidente de seguridad (27 ago 2026)

Una API key de Anthropic quedó expuesta en texto plano dos veces en una sesión de Claude Code: primero pegada directo en el chat, después visible en una captura de pantalla de PowerShell. Se le indicó a Dario revocarla en `console.anthropic.com` y generar una nueva; quedó un recordatorio programado para el 28 ago a las 9am (hora Argentina) para confirmar que se hizo. Es el segundo incidente de exposición de credenciales del mes — el primero fue un `infisical secrets --env=dev` sin filtrar el 1 ago (documentado en `STATUS.md` de `aigis-cloud`) que volcó 10 secrets en texto plano, incluyendo varias API keys de proveedores LLM. Sin resolver a la fecha de este documento: confirmar que ambas rotaciones se completaron.
