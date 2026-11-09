"""The sandbox image grades with exactly the tool versions the project pins
(P0 D5): sandbox/Dockerfile and the `dev` extra of pyproject.toml must
agree, and the base image must be pinned by digest.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

# Python 3.11+ (the project allows 3.10, CI and the image run 3.11).
tomllib = pytest.importorskip("tomllib")

ROOT = Path(__file__).parents[2]
_TOOLS = ("pytest", "pytest-json-report", "ruff")


def _dockerfile() -> str:
    return (ROOT / "sandbox" / "Dockerfile").read_text(encoding="utf-8")


def _pins(lines: list[str]) -> dict[str, str]:
    pins = {}
    for line in lines:
        match = re.fullmatch(r"\s*([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)\s*\\?\s*", line)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def test_dev_extra_pins_the_grading_tools_exactly() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = _pins(project["project"]["optional-dependencies"]["dev"])
    assert set(_TOOLS) <= set(dev), dev


def test_dockerfile_installs_the_same_versions_as_the_dev_extra() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = _pins(project["project"]["optional-dependencies"]["dev"])
    image = _pins(_dockerfile().splitlines())
    assert {tool: image.get(tool) for tool in _TOOLS} == {tool: dev[tool] for tool in _TOOLS}


def test_dockerfile_base_is_pinned_by_digest_and_runs_non_root() -> None:
    lines = _dockerfile().splitlines()
    base = next(line for line in lines if line.startswith("FROM "))
    assert re.search(r"@sha256:[0-9a-f]{64}$", base), base
    user = [line for line in lines if line.startswith("USER ")]
    assert user and not user[-1].split()[1].startswith(("0", "root"))


# --- benchmark task dependencies (9b) -----------------------------------------

# import name -> pip distribution, for every non-stdlib, non-local module a
# benchmark task repo imports. Adding a task with a new dependency means
# adding it here AND pinning it in sandbox/Dockerfile.
_TASK_IMPORTS_TO_DIST = {"pytest": "pytest", "yaml": "pyyaml"}


def _local_modules(repo: Path) -> set[str]:
    names = set()
    for path in repo.rglob("*"):
        if path.suffix == ".py":
            names.add(path.stem)
        elif path.is_dir():
            names.add(path.name)
    return names


def _third_party_imports(repo: Path) -> set[str]:
    found = set()
    local = _local_modules(repo)
    for path in repo.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            else:
                continue
            found.update(r for r in roots if r not in sys.stdlib_module_names and r not in local)
    return found


def test_every_benchmark_task_import_is_installed_in_the_image() -> None:
    """T07 (`import yaml`) failed collection in docker in the post-fix
    benchmark: the image had no PyYAML. Every third-party import of every
    examples/tasks repo must map to a pinned package in the Dockerfile."""
    pins = _pins(_dockerfile().splitlines())
    repos = sorted((ROOT / "examples" / "tasks").glob("*/repo"))
    assert len(repos) == 8
    for repo in repos:
        for module in sorted(_third_party_imports(repo)):
            assert module in _TASK_IMPORTS_TO_DIST, (
                f"{repo.parent.name} imports {module!r}: map it in _TASK_IMPORTS_TO_DIST "
                "and pin its package in sandbox/Dockerfile"
            )
            assert _TASK_IMPORTS_TO_DIST[module] in pins, (repo.parent.name, module)


def test_the_t07_dependency_is_in_the_image() -> None:
    assert _pins(_dockerfile().splitlines()).get("pyyaml") == "6.0.2"
