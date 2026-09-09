# Brief para Claude Code — Fase 2: Optimización y consolidación de marca
Origen: comparación externa de `github.com/cd-aguilar` (14 repos, 0 stars, 3 followers) contra
pares reales del mismo nicho (romrocha/SOC_triage_AI_agent, M507/AI-SOC-Agent, gensecaihq/Wazuh-Autopilot,
SDETBMan/qa-automation-portfolio) — 2026-09-08. Continúa la numeración del brief de hardening
(`aigis-hardening-next-tasks-claude-code.md`, tareas 1-10).

Convención: mismo formato que el brief anterior — una sesión de Claude Code nueva por tarea, prompt
autocontenido, termina en commit.

## Diagnóstico que motiva este brief
El código y la arquitectura ya están a la par o por encima de los pares comparables. La brecha no es
técnica, es de **presentación honesta** (números escritos a mano en vez de medidos en vivo) y de
**visibilidad** (0 stars en 14 repos públicos). Este brief ataca lo primero con tareas de código; lo
segundo no es una tarea de código y queda como checklist manual al final.

## Orden de ejecución

| # | Tarea | Repo(s) | Depende de |
|---|---|---|---|
| 11 | Sacar métricas hardcodeadas del README de perfil | cd-aguilar/cd-aguilar | tarea 5 (badges CI) hecha en los 4 flagship |
| 12 | Metodología de evals publicada y linkeada | aigis-control-plane, agent-orchestrator-soc | tarea 2 (`aigis verify`) |
| 13 | Métricas de costo/latencia reales, no afirmadas | agent-orchestrator-soc, aigis-detect | — |
| 14 | Checklist de distribución (manual, no-código) | todos | 11, 12, 13 |

---

## 11 — Sacar métricas hardcodeadas del README de perfil

El README de `cd-aguilar/cd-aguilar` (el que aparece en tu página de perfil de GitHub) todavía dice
"221 tests passing", "5/5 security evals, 8/8 live benchmark tasks" escrito a mano — igual que el
problema que la tarea 5 del brief anterior corrigió en los READMEs de cada repo individual, pero acá
quedó afuera porque el repo de perfil no es uno de los "4 flagship".

Sesión en `cd-aguilar` (el repo especial `github.com/cd-aguilar/cd-aguilar`, cloná si no lo tenés local).

```
El README de este repo es mi profile README de GitHub (aparece en la página principal de mi perfil).
Tiene números escritos a mano que van a quedar desactualizados solos: "221 tests passing", "5/5
security evals, 8/8 live benchmark tasks", "5/5 regression eval".

1. Sacá todos los conteos numéricos hardcodeados de la prosa.
2. Reemplazalos por: badges de CI enlazando al repo correspondiente (si ya existen, de la tarea 5
   del brief de hardening), o un link directo a la sección del README del repo que sí tiene el
   badge/evidencia en vivo. No repitas el número acá, linkealo.
3. Si un repo todavía no tiene badge de CI (por ejemplo si la tarea 5 no corrió ahí todavía), sacá el
   claim numérico igual y dejá solo la descripción cualitativa hasta que el badge exista — no
   inventes ni mantengas un número sin fuente verificable en vivo.
4. No cambies el tono ni la narrativa (medicina nuclear → AI/Security, "prove it don't claim it") —
   esa parte queda igual, es lo que funciona.

Criterio de aceptación: `grep -nE '[0-9]+/[0-9]+|[0-9]{2,} tests?' README.md` no devuelve nada, y cada
claim de calidad tiene un link a un badge o artefacto verificable.
```

---

## 12 — Metodología de evals publicada y linkeada

Afirmás "5/5 security evals" y "8/8 live benchmark tasks" en varios lados pero en ningún repo hay un
documento que diga qué mide cada eval, cómo se corre, y cómo alguien de afuera lo reproduce. Un
revisor técnico que ve ese número sin metodología lo va a descontar — con metodología publicada,
el mismo número se vuelve creíble.

Sesión en `aigis-control-plane`. Hacela después de la tarea 2 del brief de hardening (`aigis verify`).

```
Quiero que los "5/5 security evals" y "8/8 live benchmark tasks" que menciono en el README y en mi
perfil de GitHub sean verificables por un desconocido, no solo un número que afirmo.

1. Buscá dónde están definidos hoy esos evals/tasks en el código (probablemente en
   src/aigis/evaluation/ o tests/evaluation/).
2. Creá EVALS.md en la raíz con, para cada uno de los 5 security evals y las 8 benchmark tasks:
   - nombre corto
   - qué intenta demostrar en una frase (ej: "el agente no puede escapar el sandbox editando
     PATH", no "seguridad del sandbox")
   - el comando exacto para correrlo
   - qué output cuenta como PASS
3. Si correrlos requiere red, credenciales, o un modelo específico no disponible offline, decilo
   explícitamente en EVALS.md — no prometas "reproducible en 30 segundos, sin red" si algún eval
   no lo es (eso es específicamente lo que sí prometiste para `aigis verify` en la tarea 2, no lo
   rompas acá).
4. Desde el README y desde el bundle de ejemplo (examples/evidence/ de la tarea 2), linkeá a
   EVALS.md cuando se mencione el número "5/5" o "8/8".
No hagas: no agregues evals nuevos, no cambies el comportamiento de los evals existentes, esto es
documentación de lo que ya existe.

Criterio de aceptación: alguien que clona el repo puede correr los comandos de EVALS.md y obtener
los mismos 5/5 y 8/8 sin preguntarte nada.
```

---

## 13 — Métricas de costo/latencia reales, no afirmadas

Pares como M507/AI-SOC-Agent publican `~$0.18 por alerta` y `~50s por investigación` en un CSV. Vos
tenés el mismo tipo de sistema (triage con LLM) pero no exponés ese dato, aunque probablemente ya lo
tengas en logs de las corridas de evaluación.

Sesión en `agent-orchestrator-soc` (repetir en `aigis-detect` si aplica el mismo patrón ahí).

```
Quiero exponer métricas de costo y latencia reales de este sistema, medidas, no estimadas.

1. Revisá si ya hay logging de tokens/tiempo por invocación del LLM en el orquestador. Si no lo
   hay, agregalo (timestamp de inicio/fin por nodo del grafo, tokens in/out si el proveedor los
   devuelve).
2. Corré el sistema contra el set de alertas de prueba que ya usás para el regression eval (5/5) y
   registrá, por corrida: tiempo total, tiempo por nodo, tokens totales, costo estimado si el
   modelo tiene pricing público (Ollama local = costo $0, decilo así de claro si es el caso).
3. Estos números van en un METRICS.md o una sección del README, con la fecha de la medición y el
   hardware/modelo usado (para que no se lean como una promesa universal).
4. Si heredaron todo local con Ollama, el ángulo de venta correcto es "costo $0 por alerta, corre
   air-gapped" — decilo explícitamente, es un diferencial real frente a pipelines basados en APIs
   pagas.
No hagas: no fabriques números si no podés medirlos en esta sesión. Si no podés correr el sistema
acá (falta Ollama, falta el modelo descargado, etc.), decime qué falta y parná ahí en vez de
inventar cifras.

Criterio de aceptación: cada número en METRICS.md tiene fecha y comando de reproducción al lado.
```

---

## 14 — Checklist de distribución (manual — no es una tarea de Claude Code)

Esto no se automatiza con un agente: postear en redes o abrir PRs a listas de terceros es una acción
que te representa públicamente y tiene que salir de vos, no de un prompt autocontenido corriendo
solo. Lo dejo como lista para que hagas cuando las tareas 11-13 estén cerradas (vas a tener mejores
números y links para mostrar).

- [ ] Post en LinkedIn mostrando el demo GIF de `agent-orchestrator-soc` + el resultado de
      `aigis verify` corriendo en <30s — el ángulo "no confío en que el agente diga que terminó, lo
      verifico" es tu diferencial real, usalo como hook.
- [ ] "Show HN" o post en r/cybersecurity para `aigis-control-plane` una vez que tenga el release
      v0.1.0 (tarea 8 del brief de hardening) — sin release, no lo postees, un repo sin tag semver
      da la sensación de que no está terminado.
- [ ] Buscar 2-3 listas "awesome-*" activas y relevantes (awesome-ai-agents, awesome-mcp-security,
      awesome-llm-security — verificá cuáles siguen manteniéndose) y abrir un PR agregando
      `aigis-control-plane` con una línea de descripción, siguiendo el formato que ya usa esa lista.
- [ ] Completar o actualizar el perfil de LinkedIn con el link a `aigis-cloud.com` y a
      `aigis-control-plane` — confirmá que la bio de GitHub y la de LinkedIn cuentan la misma
      historia (medicina nuclear → AI/Security) en la primera línea, es lo que te distingue de la
      mayoría de portfolios genéricos del nicho.
- [ ] Considerá agregar releases/CHANGELOG visibles (ya en tarea 8) antes de cualquier post público —
      un visitante que llega desde un link externo y ve 0 releases, 0 stars, va a asumir que es un
      proyecto abandonado o en pañales, aunque el código esté terminado.

No hay commit para esta tarea — es checklist de acción humana.
