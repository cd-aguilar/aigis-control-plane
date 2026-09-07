# Dev Container

Reproducible environment for `aigis-control-plane`, including a working
Docker daemon inside the container (via `docker-in-docker`) so `DockerSandbox`
can run `docker run --rm --network none --user 1000:1000 --read-only ...`
without touching the host's Docker Desktop.

## Open it

1. Install the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
   in VS Code (and have Docker Desktop running on the host).
2. Open this repo in VS Code, then **Reopen in Container** (Command Palette →
   "Dev Containers: Reopen in Container").
3. First build installs the base image, the `docker-in-docker` feature, and
   runs `pip install -e ".[dev]"` + `docker pull python:3.11-slim` — a few
   minutes on the first run, seconds after that.

## Pass the API key

The container reads `ANTHROPIC_API_KEY` from your **host** environment
(`remoteEnv` in `devcontainer.json` maps `${localEnv:ANTHROPIC_API_KEY}`) — it
is never hardcoded or committed. Set it on the host before opening the
container:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # PowerShell: $env:ANTHROPIC_API_KEY = "sk-ant-..."
```

If VS Code was already open, rebuild the container after setting it so the
new env var is picked up.

## Verify Docker works inside the container

```bash
docker info
```

Should print a working daemon (no `Cannot connect to the Docker daemon`
error). If it fails, rebuild the container — `docker-in-docker` needs a
one-time daemon startup on first boot.

## Smoke test

```bash
pytest -q
```

Should be green, same as on the host — including the Docker-backed sandbox
test (`tests/sandbox/test_docker_sandbox.py::test_run_command_executes_inside_container`),
which only runs when a Docker daemon is actually reachable. See the root
`README.md` for the one-command portfolio demo (`make demo`).
