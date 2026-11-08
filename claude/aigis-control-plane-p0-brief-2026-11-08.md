# AIGIS Control Plane — Brief P0 para Claude Code (8 nov 2026)

Reemplaza los briefs del 22/9 y el de hoy anterior. Abierto en `Proyectos/06-Consultora-Aigis/aigis-control-plane/`.

## Quién escribe

Vos sos la sesión que commitea en `main`. La sesión de Claude Code de escritorio (la que armó este brief) queda como revisora, de solo lectura. Confirmalo con Dario si ves señales de otra sesión escribiendo. **No pushees**: el push lo hace Dario.

## Archivos (ya están en el disco, sin commitear)

- `docs/security/P0-design.md` — diseño aprobado, tests de §4, claims de §7, criterios de cierre de §8.
- `docs/security/P0-review.md` — hallazgos H1-H11, clasificación de controles y PoC.

Leelos completos antes de tocar código. Si algo de este brief contradice `P0-design.md`, gana `P0-design.md` salvo que Dario diga otra cosa.

## Estado real del repo

- `main` = `d5dbc5f`, 3 commits adelante de `origin/main` (`8263865`): `838e7bd` (quita `RLIMIT_NPROC`), `43b1456` (CI mínima), `d5dbc5f` (rotación de credenciales confirmada en STATUS).
- Antes: `9b19879` (3 regresiones xfail estrictas) y `8263865` (STATUS con el P0 abierto).
- Hecho: rotación confirmada (criterio 9), CI creada, D1 y D6 aprobados por Dario.
- Abierto: todo el fix del P0. Las métricas 8/8 son "baseline pre-fix".

Los 3 xfail que ya existen y que NO hay que duplicar:
- `tests/policy/test_executor.py::test_run_command_cannot_leak_a_forbidden_path` (equivale a §4 test 4, a nivel executor)
- `tests/policy/test_executor.py::test_run_command_write_is_reported_as_a_changed_path` (equivale a §4 tests 5/6, parcial)
- `tests/test_p0_command_bypass.py::test_run_command_bypass_still_yields_pass` (el PoC e2e; criterio 2 de §8)

Si un test nuevo de §4 cubre la misma propiedad, reutilizá o renombrá el existente en vez de agregar uno paralelo.

## Paso 0 — punto bloqueante antes del push: verificado, ya no bloquea

El brief del revisor decía que `test_run_command_executes_inside_container` fallaría en CI por UID. Se reprodujo con un volumen Docker nombrado (permisos Linux reales):

| Comando en contenedor | `--user 1000:1000` | `--user 1001:1001` |
|---|---|---|
| `python -c "print('ok')"` (lo que hace ese test) | funciona | funciona |
| `os.listdir('.')` | Permission denied | funciona |
| `open('a.py')` | Permission denied | funciona |

Conclusiones:
1. Ese test en particular debería pasar en CI (el `print` no toca el directorio). **No bloquees el push por esto.**
2. El bug es real: con un uid distinto de 1000, dentro de Docker no se puede leer nada del workspace, así que los gates (`pytest tests/`, `ruff check .`) fallarían en Docker sobre Linux nativo.
3. Qué hacer: anotarlo en STATUS como hallazgo para D5 (commit 8) con la opción (a): `--user {os.getuid()}:{os.getgid()}` si el host no es root (fallback a 1000 si es root, para mantener non-root). Agregar entonces un test que haga `listdir` o lea un archivo, no un `print`. No lo apliques antes de D5 sin que Dario lo elija.
4. Agregar `docker pull python:3.11-slim` antes de `pytest` en `.github/workflows/ci.yml` es barato y razonable (el pull cuenta dentro del timeout de 30 s del test). Esto sí podés hacerlo ahora.
5. Limitaciones de la verificación: no se comprobó el modo 0700 de `tmp_path` ni el `copystat` de `copytree`, y se probó en Docker Desktop, no en el runner real. Si el primer run de CI sale rojo, mirá primero ahí.

## Orden de trabajo

1. `docs(security): add original P0 design and review` — commitear los dos archivos de `docs/security/` tal cual están.
2. STATUS.md: reemplazar el checklist reconstruido por los 9 criterios del §8 de `P0-design.md`. Al reconstruido le faltaban: tests en local y docker; PoC adaptado como test de integración (FAIL/DENY); `scope_ok`/`max_files_changed` solo desde cambios observados; reporte del gate fuera del workspace; CLI con docker por defecto y modo local registrado en la evidencia; benchmark re-corrido y publicado; docs verificables con `grep`. D6 es P1 y no es criterio de cierre. El criterio 9 ya está cumplido. Hacerlo junto con el commit 1 o aparte.
3. Commit 1b — `test(security): remaining P0 §4 regressions + S06/S07/S08 (xfail strict)`: los tests 1-16 y S06/S07/S08 de §4 que falten, como `xfail(strict=True)`, sin duplicar los 3 existentes. Agregar `graphify-out/` al `.gitignore` si todavía no está (revisá `git status`: regenerable, 3.2 MB) y commitear `.devcontainer/devcontainer-lock.json` si sigue sin seguimiento (fija docker-in-docker por digest). Confirmá con Dario si dudás.
4. Commit 2 — `docs(security): scope down unverified claims`: todo el §7 de `P0-design.md` más lo siguiente.
   - `docs/THREAT-MODEL.md:14` "Resource exhaustion | CPU/memory/PID/time limits": el límite de PID existe solo en docker y el default es local (el commit `838e7bd` quitó `RLIMIT_NPROC`).
   - Docstring de `_apply_resource_limits` en `src/aigis/sandbox/local_cow.py`: todavía menciona "PID" y se contradice con el párrafo de abajo. Es solo un docstring; va en este commit.
   - `docs/ARCHITECTURE.md` §11: "PID/process limits" → aclarar que aplica solo a `DockerSandbox`.
   - `docs/SECURITY.md`: "verificado contra un daemon Docker real" vale solo para Docker Desktop/Windows; nunca se probó el modelo de permisos en Linux nativo. Los límites POSIX de `LocalCowSandbox` nunca se ejercieron en una corrida real (el benchmark 8/8 fue en Windows).
   - Quitar "unique", "tamper-proof", "production-ready", "inmutable" y "network disabled" sin calificar; verificable con `grep`.
   - README: "Known limitations" y badge de CI.
   - THREAT-MODEL: AARM informal gap analysis (R1, R3, R9 en 🟡; R5 ⬜/🟡), verificando cada uno contra el código.
5. Limpieza de STATUS.md (con el commit 2 o con el 1b):
   - Renombrar "Commit 2a" → "Fix fuera de plan (pre-CI)", para que "commit 2" siga significando recortar claims.
   - Encabezado de la línea 3: no menciona CI ni la rotación.
   - Conteo viejo de tests (234/233/1): hoy 238 recolectados (Linux 234 passed / 3 xfailed / 1 skipped). Verificarlo corriendo `pytest --collect-only -q`.
   - Donde dice que CI/CD es Fase 7 o fue rechazado: agregar que la CI mínima se adoptó el 22/9.
   - Notas de "commits sin pushear (29 ago)" ya resueltas el 7/9.
6. Commits de fix, en este orden (numeración de `next-tasks`): 4 D4 → 5 D2 → 6 D3 → 7 D1 → 8 D5 → 9 D6 → 10 benchmark. Cada commit retira los xfail que le tocan según `P0-design.md` §6.

## P1 (anotar en STATUS, no implementar ahora)

- `LocalCowSandbox.run_command` sin `start_new_session=True`: ante un timeout mueren solo los hijos directos; los nietos sobreviven y pueden colgar `communicate()` si heredaron los pipes. Fix: `start_new_session=True` + `os.killpg` en el timeout, con test.
- CI: fijar `actions/checkout` y `actions/setup-python` por commit SHA.
- `pyproject.toml`: `ruff>=0.6` sin fijar; un release nuevo puede poner el CI en rojo sin cambio de código. Fijar `ruff==<versión local>` (y, si Dario quiere, pytest y pytest-json-report).
- Bug Docker/UID del Paso 0 (ver arriba).

## Dato para D1 (commit 7)

Grep sobre `evidence/*/trace.jsonl`, 15 corridas: 15× `pytest tests/` y 15× `ruff check .`, todas tool calls del agente. Un `grep -o` sobre la línea cuenta doble porque cada línea repite el request dentro de `policy_decision.request`; contá solo `tool_request`. Los gates NO pasan por el trace. Nunca apareció `python` ni nada con flags extra. Cubre solo los bundles de esta máquina.

## Reglas

- Cada commit pasa `pytest -q` y `ruff check .`. Si no, no se commitea.
- Regresiones primero como `xfail(strict=True)`; cada commit de fix retira las suyas.
- No tocar `src/aigis/agent/runtime.py` ni `reducer.py`. Sí se puede tocar `src/aigis/policy/` y `src/aigis/agent/tools.py`.
- No commitear `.env`. Correr `git status` después de cada `git add`.
- Nada de `amend` ni `push`. Si una decisión de diseño no está en `P0-design.md`, preguntale a Dario antes.
- NO hacer: release v0.1.0, branch protection, CodeQL, Dependabot, API HTTP, UI, `ruff format` masivo, `receipt.json` firmado (P3).
- Actualizar STATUS.md en cada commit (hallazgo P0 abierto, checklist de §8 y hash).

## Trampas técnicas que ya nos pisaron

- `ToolRequest` rechaza `;`, `|`, `&&`, `` ` ``, `$(` y `\n` en `executable` y `args`. Los tests pre-siembran los scripts con `sandbox.write_file` o `setup_files` en vez de `python -c` multi-sentencia.
- `run_task` usa `PolicyEngine(contract)` con la `policy.yaml` por defecto (`python`, `python3`, `pytest`, `ruff`), así que ahí el ejecutable tiene que ser `"python"`, no `sys.executable`. En los tests de executor se pasa un `PolicyConfig` propio y sí se puede usar `sys.executable`.
- En Windows con Git Bash, `docker run ... -w /ruta` reescribe la ruta: usá `MSYS_NO_PATHCONV=1`.
- `pythonpath = ["scripts"]` ya está en `pyproject.toml`.

## Reporte por commit

```
Commit N — <nombre>
Hash: <hash> <mensaje>
Tests: <n> passed, <n> xfailed, <n> skipped | ruff: clean | CI: <verde/rojo/n.a.>
Archivos: <lista corta>
Decisiones que tomé sin preguntar: <lista o "ninguna">
Pendiente para Dario: <lista o "nada">
```

## Pendiente de Dario

- Hacer el `git push` (3 commits locales más los que vengan) y mirar el primer run de CI.
- Elegir opción para el bug Docker/UID cuando se llegue a D5 (a: `--user` con el uid del host; b: xfail con motivo).
- Después del commit 7: correr el benchmark completo (commit 10); lo corre Dario porque necesita la API key.
