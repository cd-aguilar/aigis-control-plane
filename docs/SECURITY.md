# AIGIS Control Plane — Security

_Desglosado de `ARCHITECTURE.md` el 2026-08-29. Este documento resume la postura de seguridad del proyecto y cómo está implementada; ver `THREAT-MODEL.md` para qué amenazas se cubren y `EVALUATION.md` para la evidencia reproducible de cada control._

## Postura

AIGIS Control Plane parte de que el agente de IA es un componente no confiable: puede proponer y ejecutar acciones, pero no tiene autoridad para autorizarlas ni para decidir si una tarea quedó terminada. Esa autoridad vive en el control plane, determinista y externo al LLM.

La afirmación de seguridad del proyecto es deliberadamente acotada: **"AIGIS reduces and contains agent risk through layered controls."** Nunca "AIGIS makes agents secure" ni "AIGIS is impossible to attack" — ver `THREAT-MODEL.md` para la lectura honesta de qué está cubierto, qué es parcial y qué queda fuera de alcance por diseño.

## Principios de diseño

- **Deny by default** — las acciones no autorizadas se rechazan. La autorización debe ser explícita, determinista, auditable y reproducible; nunca se delega en un LLM la pregunta de si una acción es "probablemente segura".
- **Least privilege** — el agente recibe solamente las capacidades necesarias para la tarea (`read_file`, `patch_file`, `run_command` con allowlist), nunca acceso genérico al sistema, a la red o a credenciales.
- **Evidence over claims** — el sistema confía en diff, tests, lint, policy decisions, trace de ejecución y metadata de entorno. No confía en que el agente diga que terminó (`AgentClaim` existe en el domain model, pero el Decision Engine nunca lo lee).
- **Fail closed** — cuando el sistema no puede determinar con suficiente confianza si una acción está permitida o si una tarea quedó correctamente completada, la resolución por defecto es `DENY` o `NEEDS_HUMAN`, nunca conceder autoridad implícita.
- **Minimize blast radius** — el objetivo no es demostrar seguridad absoluta, sino reducir y contener el radio de impacto de un agente autónomo a través de controles en capas: autorización explícita, aislamiento, límites de recursos y evidencia verificable.

## Controles implementados

### Policy Engine

Determinista y externo al LLM (`src/aigis/policy/`): `ToolRequest → PolicyEngine.evaluate() → PolicyDecision` (`ALLOW`/`DENY`/`REQUIRE_HUMAN`). Reglas evaluadas en orden fijo, primera que matchea, fail-closed: el `risk_level` del contrato (`CRITICAL` deniega todo, `HIGH` exige humano) se evalúa antes que cualquier regla de path o comando; para lectura/edición de archivos, traversal o rutas absolutas se deniegan primero, después `forbidden_paths`, después `allowed_paths` con deny-by-default; para comandos, `..` en cualquier argumento se deniega primero, después un allowlist de ejecutables (`policy/policy.yaml`, editable sin tocar código) con deny-by-default. Cada `PolicyDecision` incluye `policy_version` — un hash SHA-256 (12 hex) de la `PolicyConfig` efectivamente cargada — para poder atar cualquier decisión individual a la allowlist exacta que la produjo, sin cruzar contra otro archivo.

### Sandbox

Ejecución aislada (`src/aigis/sandbox/`), dos implementaciones del mismo protocolo:

- **`LocalCowSandbox`** — copia efímera copy-on-write (`shutil.copytree`), límites de recursos POSIX (CPU/memoria/procesos vía `resource.setrlimit`), diff unificado contra el repo base. No aísla red ni usuario — es honesto sobre esa limitación en su propio docstring, no la esconde.
- **`DockerSandbox`** — reusa `LocalCowSandbox` para filesystem y ejecuta cada comando en un contenedor `docker run --rm` efímero: `--network none`, `--user 1000:1000`, `--read-only` + `--tmpfs /tmp`, límites de memoria/CPU/PIDs. Verificado contra un daemon Docker real, no solo con argv mockeado.

`SandboxedToolExecutor` corre `PolicyEngine.evaluate()` antes de cualquier ejecución — un `DENY`/`REQUIRE_HUMAN` nunca llega al sandbox.

### Comandos como argv, nunca shell string

`ToolRequest` estructura `run_command` como `{"executable": "pytest", "args": ["tests/"]}`, nunca como `{"command": "pytest tests/ && rm -rf ..."}` — esto elimina una clase completa de command injection por construcción, no por filtrado posterior de metacaracteres. Es un validador Pydantic, no una convención de estilo.

### Evidence Bundle

Cada corrida produce un `evidence/<run-id>/` inmutable (`manifest.json`, `task.json`, `trace.jsonl`, `state.json`, `events.jsonl`, `diff.patch`, `test-report.json`, `lint-report.json`, `security-report.json`, `environment.json`, `hashes.json`, `decision.json`) con SHA-256 por artefacto en `hashes.json`. `environment.json` registra `model`, `model_version`, `policy_version`, `git_commit`, `sandbox_image` y (desde el 29/08) tokens consumidos — suficiente para reconstruir el contexto exacto de una corrida sin depender de que nadie lo recuerde.

## Qué no cubre esta postura

Multi-agente, multi-provider real, GitHub write access, Credential Broker completo, aprobación humana con UI real, monitoreo de comportamiento entre corridas — todo Fase 7, explícitamente fuera del alcance inicial. Ver `THREAT-MODEL.md` para el detalle ítem por ítem contra OWASP ASI Top 10 2026, y `ARCHITECTURE.md` sección 21 para el alcance completo.

## Reportar un problema

Este es un proyecto de portfolio individual, sin bug bounty ni SLA de respuesta. Si encontrás un problema de seguridad real (no solo un gap ya documentado arriba como fuera de alcance), abrí un issue en el repo o contactá directamente al autor — no hay superficie de exposición pública además del propio repositorio (no hay despliegue corriendo, no hay credenciales de valor en el código, ver `THREAT-MODEL.md`).
