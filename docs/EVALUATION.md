# AIGIS Control Plane — Evaluation

_Desglosado de `ARCHITECTURE.md` secciones 17-19 el 2026-08-29. Ver `THREAT-MODEL.md` para qué amenaza prueba cada security eval, `docs/DEMO.md` para el transcript real sin editar de las 8 corridas del benchmark._

## Security Evaluation Suite

La seguridad forma parte del sistema de evaluación, no es documentación decorativa.

**Completo (2026-08-29):** S01 — Prompt Injection, S02 — Unauthorized Secret Access, S03 — Path Traversal, S04 — Command Injection, S05 — Resource Exhaustion. Las 5 evals originalmente planeadas están implementadas en `src/aigis/evaluation/security_suite.py`.

Flujo ejemplo (S01-S04): malicious README → agent reads it → agent attempts forbidden action → Policy Engine → DENY → evidence → security evaluation PASS. S05 no encaja en ese flujo — no hay una request que denegar, sino un agente que nunca decide parar por su cuenta; lo que se verifica ahí es que el circuit breaker del contrato (`max_iterations`/`max_tool_calls`/`max_runtime_seconds`, ver `THREAT-MODEL.md` fila "Infinite agent loop") termina el run de forma determinista, sin depender del safety cap absoluto de `AgentRuntime` (que es un backstop, no el mecanismo primario).

La métrica debe hablar de **"containment against the tested attack set"**, nunca de "100% secure".

## Evaluation Suite funcional (benchmark)

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

## Métricas

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

Las 8 tareas de benchmark, corridas una vez cada una contra la API real de
Claude (`aigis run examples/tasks/T0N/contract.json
examples/tasks/T0N/repo`), agregadas con
`python scripts/aggregate_metrics.py --all`:

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
| Containment rate | N/D — cero acciones no-ALLOW; no hay nada que contener en un benchmark funcional sin condición adversarial scripteada (para eso está la Security Suite) |

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

### Segunda pasada (N>1 por tarea) — en curso

Al 2026-08-29, varias tareas ya tienen más de una corrida real acumulada en
`evidence/` (T01-T05 y T07 entre 2 y 3 corridas; T06 y T08 siguen en N=1 —
precisamente las que más interesa repetir, porque T06 es el outlier de la
tabla de arriba y T08 es el único otro dato sin segundo punto de
comparación). `scripts/aggregate_metrics.py --all --per-task` agrupa por
`task_id` y reporta `output_tokens_spread` (min, max) por tarea — un spread
`(x, x)` significa "todavía una sola corrida, no hay nada que leer ahí
todavía"; un spread real es lo que separa "T06 es estructuralmente más caro"
de "esa corrida fue ruido". Para completar la segunda pasada: correr T06 y
T08 (idealmente también una tercera corrida de las que ya tienen 2, para
más señal) con `aigis run examples/tasks/T0N/contract.json
examples/tasks/T0N/repo` contra la API real, después
`python scripts/aggregate_metrics.py --all --per-task` para leer el
resultado agrupado.
