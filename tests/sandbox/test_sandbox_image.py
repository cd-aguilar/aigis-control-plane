"""The sandbox image grades with exactly the tool versions the project pins
(P0 D5): sandbox/Dockerfile and the `dev` extra of pyproject.toml must
agree, and the base image must be pinned by digest.
"""

from __future__ import annotations

import re
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
