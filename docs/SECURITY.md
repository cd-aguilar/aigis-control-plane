# AIGIS Control Plane — Security

_Desglosado de `ARCHITECTURE.md` el 2026-08-29. Este documento resume la postura de seguridad del proyecto y cómo está implementada; ver `THREAT-MODEL.md` para qué amenazas se cubren y `EVALUATION.md` para la evidencia reproducible de cada control._

## Postura

AIGIS Control Plane parte de que el agente de IA es un componente no confiable: puede proponer y ejecutar acciones, pero no tiene autoridad para autorizarlas ni para decidir si una tarea quedó terminada. Esa autoridad vive en el control plane, determinista y externo al LLM.

La afirmación de seguridad del proyecto es deliberadamente acotada: **"AIGIS reduces and contains agent risk through layered controls."** Nunca "AIGIS makes agents secure" ni "AIGIS is impossible to attack" — ver `THREAT-MODEL.md` para la lectura honesta de qué está cubierto, qué es parcial y qué queda fuera de alcance por diseño.

> **P0 abierto (desde el 22 sep 2026).** Hoy AIGIS **no** puede afirmar que impide el acceso a secretos, que restringe el alcance de los cambios ni que verifica la tarea de forma independiente del agente: un `run_command` con `python` (permitido por la allowlist por defecto) lee rutas prohibidas, escribe fuera de alcance sin quedar registrado y reescribe los tests que después califica el gate, y la decisión da `PASS`. Hallazgos: `docs/security/P0-review.md`. Diseño del fix (D1-D6) y criterios de cierre: `docs/security/P0-design.md`. Las secciones de abajo describen los controles como están implementados hoy, con sus límites.

## Dos dominios de confianza

- **Dominio del agente (no confiable):** todo lo que el agente puede escribir o hacer ejecutar — el workspace del sandbox y el código que corre un `run_command`. Desde D3 **no** incluye los insumos de los gates (ver abajo).
- **Dominio del control plane (confiable):** el contrato, la policy, el repo base de solo lectura, los insumos protegidos de los gates, el directorio de reportes y el Decision Engine. Principio del fix del P0: **la decisión solo puede depender de datos que el agente no puede escribir.**

### Insumos de los gates (D3, 9 nov 2026)

- **`protected_paths`** en `TaskContract`. Default: `tests/`, `pytest.ini`, `.pytest.ini`, `setup.cfg`, `tox.ini` en la raíz y, **por nombre en cualquier nivel**, `conftest.py`, `pyproject.toml`, `ruff.toml` y `.ruff.toml`. Los configs de ruff van por nombre porque ruff usa el config más cercano a cada archivo: un `src/ruff.toml` apaga el lint de `src/` aunque el de la raíz siga intacto (verificado con ruff 0.16). Un validador impide que `allowed_paths` se solape con `protected_paths`.
- **Solo lectura para el agente:** `read_file` sobre un protegido da ALLOW; `patch_file` da DENY `PATH-004`, incluso dentro de un prefijo permitido (`src/conftest.py`).
- **Workspace de evaluación:** después del turno del agente, el sandbox se reconstruye **desde la base** (menos lo excluido por D2), más los cambios observados del agente fuera de los protegidos. No se copia el workspace del agente para "restaurar" los protegidos, así que un protegido que el agente creó, borró, modificó o reemplazó por un symlink se pierde. Los symlinks que creó el agente tampoco pasan, en ningún path, porque un gate podría seguirlos hasta un archivo del host. Todo cambio de un protegido da FAIL `protected_path_modified`.
- **Reporte fuera del workspace:** el orquestador crea un directorio de reportes fuera del workspace de evaluación. Pytest escribe ahí y el gate lo lee con una lectura del host, nunca con `sandbox.read_file`, así que un reporte plantado en el workspace se ignora.
- **Gate que no puede correr → `NEEDS_HUMAN gate_infrastructure_error`:** se distingue por exit code y por la existencia del reporte, nunca por texto. Sin reporte y con exit 126/127 (no encontrado) o 4 (error de uso de pytest, p. ej. falta `pytest-json-report`), o ruff con un exit distinto de 0/1. Un test que falla de verdad (con reporte) sigue siendo FAIL. Un reporte faltante después de que pytest corrió también es FAIL.

**Límite, no garantía:** pytest importa `src/`, así que **el código del agente corre dentro del proceso del gate**. Desde un import puede monkeypatchear pytest, escribir o borrar el archivo de reporte (el directorio está fuera del workspace, pero el proceso tiene permiso de escritura) o alterar lo que reportan los tests. D3 cierra lo que el agente deja escrito en el workspace, no lo que su código hace mientras se lo evalúa. Cerrar eso requiere aislar el proceso que califica del código calificado. D5 (contenedor por defecto) es un paso en esa dirección pero no lo resuelve solo. En modo docker, además, el directorio de reportes todavía no se monta en el contenedor (queda para D5). Hoy eso no cambia el resultado: `python:3.11-slim` no trae pytest, `docker run` sale con 127 (verificado el 9/11) y el gate termina en `gate_infrastructure_error`.

## Principios de diseño

- **Deny by default** — las acciones no autorizadas se rechazan. La autorización debe ser explícita, determinista, auditable y reproducible; nunca se delega en un LLM la pregunta de si una acción es "probablemente segura".
- **Least privilege** — el agente recibe solamente las capacidades necesarias para la tarea (`read_file`, `patch_file`, `run_command` con allowlist), nunca acceso a credenciales. _Límite actual (P0): la allowlist por defecto incluye `python`/`python3`, que son intérpretes universales, así que `run_command` equivale hoy a ejecución genérica de código dentro del workspace; en modo local, ese código además tiene red y ve el filesystem del host. D1 reemplaza `run_command` por `run_tests`/`run_lint` sin argumentos libres._
- **Evidence over claims** — el sistema confía en diff, tests, lint, policy decisions, trace de ejecución y metadata de entorno. No confía en que el agente diga que terminó (`AgentClaim` existe en el domain model, pero el Decision Engine nunca lo lee).
- **Fail closed** — cuando el sistema no puede determinar con suficiente confianza si una acción está permitida o si una tarea quedó correctamente completada, la resolución por defecto es `DENY` o `NEEDS_HUMAN`, nunca conceder autoridad implícita.
- **Minimize blast radius** — el objetivo no es demostrar seguridad absoluta, sino reducir y contener el radio de impacto de un agente autónomo a través de controles en capas: autorización explícita, aislamiento, límites de recursos y evidencia verificable.

## Controles implementados

### Policy Engine

Determinista y externo al LLM (`src/aigis/policy/`): `ToolRequest → PolicyEngine.evaluate() → PolicyDecision` (`ALLOW`/`DENY`/`REQUIRE_HUMAN`). Reglas evaluadas en orden fijo, primera que matchea, fail-closed: el `risk_level` del contrato (`CRITICAL` deniega todo, `HIGH` exige humano) se evalúa antes que cualquier regla de path o comando; para lectura/edición de archivos, traversal o rutas absolutas se deniegan primero, después `forbidden_paths`, después `allowed_paths` con deny-by-default; para comandos, `..` en cualquier argumento se deniega primero, después un allowlist de ejecutables (`policy/policy.yaml`, editable sin tocar código) con deny-by-default. Cada `PolicyDecision` incluye `policy_version` — un hash SHA-256 (12 hex) de la `PolicyConfig` efectivamente cargada — para poder atar cualquier decisión individual a la allowlist exacta que la produjo, sin cruzar contra otro archivo.

### Sandbox

Ejecución aislada (`src/aigis/sandbox/`), dos implementaciones del mismo protocolo:

- **`LocalCowSandbox`** — copia efímera copy-on-write (`shutil.copytree`), límites de recursos POSIX (CPU/memoria vía `resource.setrlimit`; sin límite de procesos — `RLIMIT_NPROC` es por UID, no por sandbox, y rompía herramientas multi-hilo como ruff en Linux; el límite de PIDs real está en `DockerSandbox`), diff unificado contra el repo base. No aísla red, usuario ni el filesystem del host para el código que ejecuta (verificado en la revisión del 22/9: `open('/etc/hostname')` y DNS a pypi.org funcionan). Copia el repo entero, `forbidden_paths` incluidos (P0, D2). **Es el modo por defecto de `aigis run`**, y el benchmark 8/8 corrió así. Sus límites POSIX nunca se ejercieron en una corrida real: el benchmark corrió en Windows, donde no se aplican; en Linux solo los cubren los tests.
- **`DockerSandbox`** — reusa `LocalCowSandbox` para filesystem y ejecuta cada comando en un contenedor `docker run --rm` efímero: `--network none`, `--user 1000:1000`, `--read-only` + `--tmpfs /tmp`, límites de memoria/CPU/PIDs. Solo con `--sandbox docker`. Verificado contra un daemon Docker real **en Docker Desktop sobre Windows**; el modelo de permisos en Linux nativo no se probó, y hay un hallazgo abierto para D5: con un dueño del workspace distinto de uid 1000, el contenedor no puede leer el workspace. Faltan `--cap-drop ALL` y `no-new-privileges`, la imagen (`python:3.11-slim`) no está fijada por digest y no trae `pytest` ni `ruff` (D5).

`SandboxedToolExecutor` corre `PolicyEngine.evaluate()` antes de cualquier ejecución — un `DENY`/`REQUIRE_HUMAN` nunca llega al sandbox.

### Comandos como argv, nunca shell string

`ToolRequest` estructura `run_command` como `{"executable": "pytest", "args": ["tests/"]}`, nunca como `{"command": "pytest tests/ && rm -rf ..."}`, y el sandbox lo ejecuta con `subprocess.run([...])` sin `shell=True` — eso es lo que elimina la inyección de shell, por construcción. El rechazo adicional de metacaracteres en `ToolRequest` es defensa en profundidad, no el control real (y da falsos positivos, p. ej. `pytest -k "a|b"`). Esto no limita qué hace el programa ejecutado (ver el límite de least privilege arriba).

### Evidence Bundle

Cada corrida produce un `evidence/<run-id>/` (`manifest.json`, `task.json`, `trace.jsonl`, `state.json`, `events.jsonl`, `diff.patch`, `test-report.json`, `lint-report.json`, `security-report.json`, `environment.json`, `hashes.json`, `decision.json`) con un SHA-256 por artefacto en `hashes.json`. Esos hashes son **checksums sin clave ni firma**, guardados en el mismo directorio y sin cubrir `decision.json`: detectan corrupción accidental, no manipulación. Receipts firmados: planeado (P3), no implementado.

`environment.json` registra hoy `model_provider`, `model`, `task_contract_version` y (desde el 29/08) los tokens consumidos. Los campos de reproducibilidad `git_commit`, `sandbox_image`, `sandbox_image_digest`, `prompt_version`, `policy_version` y `python_version` existen en el modelo pero quedan en `null` hasta D5. (`policy_version` sí queda en cada `PolicyDecision` de `trace.jsonl`/`events.jsonl`.)

`diff.patch` se calcula comparando el filesystem, así que muestra también lo que hizo un `run_command`: es el artefacto más confiable del bundle. Hoy el Decision Engine no lo usa (P0, D4).

## Qué no cubre esta postura

Multi-agente, multi-provider real, GitHub write access, Credential Broker completo, aprobación humana con UI real, monitoreo de comportamiento entre corridas — todo Fase 7, explícitamente fuera del alcance inicial. Ver `THREAT-MODEL.md` para el detalle ítem por ítem contra OWASP ASI Top 10 2026, y `ARCHITECTURE.md` sección 21 para el alcance completo.

## Reportar un problema

Este es un proyecto de portfolio individual, sin bug bounty ni SLA de respuesta. Si encontrás un problema de seguridad real (no solo un gap ya documentado arriba como fuera de alcance), abrí un issue en el repo o contactá directamente al autor — no hay superficie de exposición pública además del propio repositorio (no hay despliegue corriendo, no hay credenciales de valor en el código, ver `THREAT-MODEL.md`).
