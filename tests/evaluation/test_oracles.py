"""v0.2 D9: validity of the 8 benchmark tasks' hidden oracles (CI-checked).

For every task: the base FAILS at least one oracle case; the reference
solution PASSES every case, pytest and ruff; the cases are disjoint from the
visible tests' inputs (except cases marked ``shared_with_visible``, each
with its justification, and at least one unshared case per task outside
``ALL_SHARED_ALLOWLIST``); ``oracle.json`` and ``solution.patch`` live next
to ``repo/``, never inside it, and match the source of truth.

The cases are evaluated here by a small in-process runner in a host
subprocess -- enough to validate the *data*. The real worker (in the sandbox
image, inputs only, comparison on the host) is plan commit 3; the
comparison rule is already the real one (``aigis.evaluation.oracle``).
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aigis.evaluation.benchmark_tasks import (
    ALL_SHARED_ALLOWLIST,
    TASKS,
    BenchmarkTask,
    materialize,
)
from aigis.evaluation.oracle import case_passes, values_match, worker_inputs

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples" / "tasks"
TASK_IDS = [factory().task_id for factory in TASKS]
_BY_ID = {factory().task_id: factory for factory in TASKS}

# Test-only runner (see module docstring). Returns one outcome per case:
# {"value": v} | {"raises": "Name"} plus {"attrs": {...}} for method cases.
_RUNNER = r"""
import importlib, json, sys
sys.path.insert(0, "src")
out = []
for c in json.load(sys.stdin):
    item = {}
    obj = None
    try:
        mod = importlib.import_module(c["module"])
        if "class" in c:
            obj = getattr(mod, c["class"])(*c["init_args"])
            item["value"] = getattr(obj, c["method"])(*c["args"], **c["kwargs"])
        else:
            item["value"] = getattr(mod, c["function"])(*c["args"], **c["kwargs"])
    except Exception as exc:
        item.pop("value", None)
        item["raises"] = type(exc).__name__
    if "class" in c and obj is not None:
        item["attrs"] = {name: getattr(obj, name) for name in c["state_attrs"]}
    out.append(item)
print(json.dumps(out))
"""


def _task(task_id: str) -> BenchmarkTask:
    return _BY_ID[task_id]()


def _materialize(task: BenchmarkTask, root: Path, *, reference: bool) -> Path:
    root.mkdir(parents=True)
    materialize(task, root)
    if reference:
        for rel, content in task.reference_files.items():
            (root / rel).write_text(content, encoding="utf-8")
    return root


def _verdicts(repo: Path, cases: list[dict]) -> list[bool]:
    completed = subprocess.run(
        [sys.executable, "-I", "-c", _RUNNER],
        cwd=repo,
        input=json.dumps(worker_inputs(cases)),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    outcomes = json.loads(completed.stdout)
    assert len(outcomes) == len(cases)
    return [case_passes(c, o) for c, o in zip(cases, outcomes, strict=True)]


# --- the comparison rule (Dario, 2026-11-15) ----------------------------------


@pytest.mark.parametrize(
    ("actual", "expected", "match"),
    [
        (0, 0.0, True),  # T03: a fix returning int 0 is valid
        (0.1 + 0.2, 0.3, True),
        (1.0000001, 1.0, False),
        (True, 1, False),
        (1, True, False),
        (True, True, True),
        (None, 0, False),
        ("a", "a", True),
        ([1, 2.0], [1.0, 2], True),
        ([1], [1, 2], False),
        ({"a": 3, "b": 30.0}, {"a": 3.0, "b": 30}, True),
        ({"a": 3}, {"a": 3, "b": 30}, False),
        ({"a": True}, {"a": 1}, False),
    ],
)
def test_values_match(actual, expected, match: bool) -> None:
    assert values_match(actual, expected) is match


def test_t03_fix_returning_int_zero_passes(tmp_path: Path) -> None:
    task = _task("T03")
    repo = _materialize(task, tmp_path / "repo", reference=False)
    (repo / "src" / "stats.py").write_text(
        "def average(numbers):\n    if not numbers:\n        return 0\n"
        "    return sum(numbers) / len(numbers)\n",
        encoding="utf-8",
    )
    assert all(_verdicts(repo, task.oracle["cases"]))


def test_rejected_withdrawal_must_leave_the_balance_unchanged(tmp_path: Path) -> None:
    task = _task("T05")
    repo = _materialize(task, tmp_path / "repo", reference=False)
    (repo / "src" / "accounts.py").write_text(
        "class Account:\n    def __init__(self, balance):\n        self.balance = balance\n\n"
        "    def withdraw(self, amount):\n        self.balance -= amount\n"
        "        if amount < 0 or self.balance < 0:\n            raise ValueError\n",
        encoding="utf-8",
    )
    verdicts = _verdicts(repo, task.oracle["cases"])
    raising = [v for c, v in zip(task.oracle["cases"], verdicts, strict=True) if "raises" in c]
    assert raising and not any(raising)


def test_worker_inputs_carry_no_expected_values() -> None:
    for factory in TASKS:
        cases = factory().oracle["cases"]
        for item in worker_inputs(cases):
            assert not {"expected", "expected_attrs", "raises", "shared_with_visible"} & set(item)
        method_inputs = [i for i in worker_inputs(cases) if "class" in i]
        for item in method_inputs:
            assert all(isinstance(name, str) for name in item["state_attrs"])


# --- validity of each task (D9) -------------------------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_oracle_is_well_formed(task_id: str) -> None:
    oracle = _task(task_id).oracle
    assert isinstance(oracle.get("notes"), str) and oracle["notes"].strip()
    assert oracle["cases"]
    for case in oracle["cases"]:
        assert {"module", "args", "kwargs"} <= set(case)
        assert ("function" in case) != ("class" in case)
        if "class" in case:
            assert {"init_args", "method", "expected_attrs"} <= set(case)
            assert "expected" not in case
        else:
            assert ("expected" in case) != ("raises" in case)
        if "shared_with_visible" in case:
            assert isinstance(case["shared_with_visible"], str)
            assert case["shared_with_visible"].strip()


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_base_fails_the_oracle(task_id: str, tmp_path: Path) -> None:
    task = _task(task_id)
    base = _materialize(task, tmp_path / "base", reference=False)
    assert not all(_verdicts(base, task.oracle["cases"]))


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_reference_passes_oracle_pytest_and_ruff(task_id: str, tmp_path: Path) -> None:
    task = _task(task_id)
    ref = _materialize(task, tmp_path / "ref", reference=True)
    assert all(_verdicts(ref, task.oracle["cases"]))
    pytest_run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/"],
        cwd=ref,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert pytest_run.returncode == 0, pytest_run.stdout + pytest_run.stderr
    ruff = shutil.which("ruff")
    assert ruff is not None
    ruff_run = subprocess.run(
        [ruff, "check", "--no-cache", "."], cwd=ref, capture_output=True, text=True, timeout=60
    )
    assert ruff_run.returncode == 0, ruff_run.stdout


# --- disjointness from the visible tests ----------------------------------------


def _literal(node: ast.AST):
    """Value of a constant expression ('a' * 21 included), or a sentinel."""
    try:
        return ast.literal_eval(node)
    except ValueError:
        pass
    try:
        code = compile(ast.Expression(node), "<visible-test>", "eval")
        return eval(code, {"__builtins__": {}}, {})  # noqa: S307 -- our own test fixtures
    except Exception:
        return _UNKNOWN


_UNKNOWN = object()


def _norm(value):
    """JSON normalization: tuples become lists, like the oracle's args."""
    return json.loads(json.dumps(value))


def _visible_inputs(task: BenchmarkTask) -> set[str]:
    """Every call to a top-level name in the visible tests, as a canonical
    key; ``Cls(a).method(b)`` chains as a method key."""
    keys: set[str] = set()
    for rel, source in task.setup_files.items():
        if not rel.startswith("tests/"):
            continue
        tree = ast.parse(source)
        scopes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)] or [tree]
        for scope in scopes:
            keys |= _scope_inputs(scope)
    return keys


def _scope_inputs(scope: ast.AST) -> set[str]:
    """One test function, statement by statement in source order: an
    ``obj = Cls(literal...)`` binds obj's constructor, so a later
    ``obj.method(...)`` is keyed like ``Cls(...).method(...)``."""
    keys: set[str] = set()
    instances: dict[str, tuple[str, list]] = {}
    for statement in getattr(scope, "body", []):
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
        ):
            init = [_literal(a) for a in statement.value.args]
            if not any(a is _UNKNOWN for a in init):
                instances[statement.targets[0].id] = (statement.value.func.id, _norm(init))
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            args = [_literal(a) for a in node.args]
            if any(a is _UNKNOWN for a in args):
                continue
            if isinstance(func, ast.Name):
                keys.add(json.dumps(["fn", func.id, _norm(args)]))
                continue
            if not isinstance(func, ast.Attribute):
                continue
            owner = func.value
            if isinstance(owner, ast.Name) and owner.id in instances:
                cls, init = instances[owner.id]
            elif isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name):
                init = [_literal(a) for a in owner.args]
                if any(a is _UNKNOWN for a in init):
                    continue
                cls, init = owner.func.id, _norm(init)
            else:
                continue
            keys.add(json.dumps(["m", cls, init, func.attr, _norm(args)]))
    return keys


def _case_key(case: dict) -> str:
    if "class" in case:
        return json.dumps(
            ["m", case["class"], case["init_args"], case["method"], case["args"]]
        )
    return json.dumps(["fn", case["function"], case["args"]])


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_cases_are_disjoint_from_visible_tests(task_id: str) -> None:
    task = _task(task_id)
    visible = _visible_inputs(task)
    assert visible, "no visible test input found: the extraction is broken"
    for case in task.oracle["cases"]:
        overlaps = _case_key(case) in visible
        if "shared_with_visible" in case:
            # a mark must be true, not a blanket exemption
            assert overlaps, f"marked shared but not in the visible tests: {case}"
        else:
            assert not overlaps, f"oracle case repeats a visible test input: {case}"
    unshared = [c for c in task.oracle["cases"] if "shared_with_visible" not in c]
    if task_id in ALL_SHARED_ALLOWLIST:
        assert ALL_SHARED_ALLOWLIST[task_id].strip()
    else:
        assert unshared, f"{task_id} needs at least one case not shared with the visible tests"


def test_visible_extraction_sees_method_chains() -> None:
    keys = _visible_inputs(_task("T05"))
    assert json.dumps(["m", "Account", [100], "withdraw", [30]]) in keys


# --- files on disk (D7/D9) ------------------------------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_oracle_and_solution_live_next_to_the_repo_not_inside(task_id: str) -> None:
    task_dir = EXAMPLES / task_id
    assert (task_dir / "oracle.json").is_file()
    assert (task_dir / "solution.patch").is_file()
    repo = task_dir / "repo"
    leaked = [
        p.relative_to(repo).as_posix()
        for p in repo.rglob("*")
        if p.name in ("oracle.json", "solution.patch")
    ]
    assert leaked == []
    for case in _task(task_id).oracle["cases"]:
        if "expected" in case and isinstance(case["expected"], str) and len(case["expected"]) > 3:
            for path in repo.rglob("*"):
                if path.is_file() and path.suffix in (".py", ".yaml", ".ini", ".toml"):
                    assert case["expected"] not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_examples_match_the_source_of_truth(task_id: str) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from generate_examples import oracle_json, solution_patch

    task = _task(task_id)
    task_dir = EXAMPLES / task_id
    assert (task_dir / "oracle.json").read_text(encoding="utf-8") == oracle_json(task)
    assert (task_dir / "solution.patch").read_text(encoding="utf-8") == solution_patch(task)
    on_disk = json.loads((task_dir / "contract.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(task.contract.model_dump_json())


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_solution_patch_applies_to_the_base_and_gives_the_reference(
    task_id: str, tmp_path: Path
) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git not available")
    task = _task(task_id)
    base = _materialize(task, tmp_path / "base", reference=False)
    patch = tmp_path / "solution.patch"
    shutil.copy(EXAMPLES / task_id / "solution.patch", patch)
    applied = subprocess.run(
        [git, "apply", "--unsafe-paths", str(patch)],
        cwd=base,
        capture_output=True,
        text=True,
    )
    assert applied.returncode == 0, applied.stderr
    for rel, content in task.reference_files.items():
        assert (base / rel).read_text(encoding="utf-8") == content


def test_disjointness_check_catches_a_repeated_visible_input() -> None:
    # Negative control: a case on the visible test's own input is a hit.
    repeated = {"module": "calculator", "function": "subtract", "args": [5, 3], "kwargs": {}}
    assert _case_key(repeated) in _visible_inputs(_task("T01"))
    method = {"module": "accounts", "class": "Account", "init_args": [100], "method": "withdraw",
              "args": [30], "kwargs": {}}
    assert _case_key(method) in _visible_inputs(_task("T05"))
