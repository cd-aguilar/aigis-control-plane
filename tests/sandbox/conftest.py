from pathlib import Path

import pytest


@pytest.fixture
def base_repo(tmp_path: Path) -> Path:
    """A tiny toy repo: one source file, one test file -- enough to exercise
    read/patch/run_command and diff collection without needing the real
    aigis-control-plane checkout as a fixture.
    """
    repo = tmp_path / "toy-repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "math_utils.py").write_text(
        "def add(a, b):\n    return a - b  # bug: should be +\n", encoding="utf-8"
    )
    (repo / "README.md").write_text("# toy repo\n", encoding="utf-8")
    return repo
