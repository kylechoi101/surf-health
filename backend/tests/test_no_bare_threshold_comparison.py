"""Guard: exceedance is decided in exactly one module.

``exceeds_stv`` is not one label. Culture rows are judged against the 104
MPN/CFU marine STV; San Diego ddPCR rows against **1413 copies/100mL**, a
CDPH-developed value approved by EPA Region 9 and the rule San Diego DEH
actually posts advisories on. Both numbers are correct and neither may be
changed. What must never happen again is a call site *picking one of them
itself*.

That bug has now been found three separate times, in three different shapes:

* ``curation.py`` -- a flat ``value > stv_threshold`` on the path that writes
  ``beach_day.parquet``;
* ``serving_repository`` / ``curated_repository`` -- the user-facing "above the
  marine threshold" driver string, computed from the raw value, contradicting
  the ``exceeds_stv`` sitting in the same row;
* ``training._persistence_probabilities`` -- a method-blind
  ``enterococcus_value_last_obs > stv_threshold`` that, while the serve path
  still hard-pinned persistence positives to 1.0, put 34 of the 74 "High" bands
  served on 2026-07-30 on beaches whose most recent lab result was clean.

So this is an AST scan, not a code-review convention: it parses every module
under ``app/`` and fails on any comparison between an enterococcus reading and
a threshold, anywhere except :mod:`app.data.pipeline.exceedance`, which is the
one module allowed to know which number applies.

**Known limit:** matching is by *name* and by *literal*. Binding the threshold
to an unrelated local first (``t = self.stv_threshold; value > t``) slips past.
That is a deliberate trade against false positives — the guard has to stay
silent on the many legitimate numeric comparisons in the ML code — and it still
catches every shape the three real defects above actually took.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# The one module permitted to compare a value against an action value.
EXEMPT_MODULES = frozenset({"app/data/pipeline/exceedance.py"})

# Names that denote an enterococcus action value. Deliberately specific: a bare
# `threshold` is not enough evidence — `evaluation.py`'s
# `probabilities >= threshold` sweeps a probability operating point, which is a
# different kind of number entirely and must not be flagged.
THRESHOLD_NAMES = frozenset(
    {
        "stv_threshold",
        "pcr_threshold",
        "epa_marine_enterococcus_stv",
        "PCR_ENTEROCOCCUS_THRESHOLD_COPIES",
        "action_value",
    }
)

# The two regulatory action values as bare literals. A comparison against one of
# these anywhere is the same defect wearing a number instead of a name.
THRESHOLD_LITERALS = frozenset({104, 104.0, 1413, 1413.0})

COMPARISON_OPS = (ast.Gt, ast.GtE, ast.Lt, ast.LtE)


def _is_threshold_expr(node: ast.expr) -> bool:
    """Whether this expression names, or is, an enterococcus action value."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return not isinstance(node.value, bool) and node.value in THRESHOLD_LITERALS
    if isinstance(node, ast.Name):
        return node.id in THRESHOLD_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in THRESHOLD_NAMES
    return False


def _python_files() -> list[Path]:
    return sorted(p for p in APP_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _violations(path: Path, repo_relative: str) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        # `a > threshold` / `threshold < a`
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(isinstance(op, COMPARISON_OPS) for op in node.ops) and any(
                _is_threshold_expr(operand) for operand in operands
            ):
                found.append(f"{repo_relative}:{node.lineno}  {ast.unparse(node)}")
        # `series.gt(threshold)` / `.lt(...)` / `.ge(...)` / `.le(...)`
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"gt", "ge", "lt", "le"} and any(
                _is_threshold_expr(arg) for arg in node.args
            ):
                found.append(f"{repo_relative}:{node.lineno}  {ast.unparse(node)}")
    return found


def test_no_module_outside_exceedance_compares_a_value_to_a_threshold() -> None:
    offenders: list[str] = []
    scanned = 0
    for path in _python_files():
        repo_relative = str(path.relative_to(APP_ROOT.parent)).replace("\\", "/")
        if repo_relative in EXEMPT_MODULES:
            continue
        scanned += 1
        offenders.extend(_violations(path, repo_relative))

    assert scanned > 50, f"scan found only {scanned} modules — the walk is broken, not the code"
    assert not offenders, (
        "enterococcus exceedance must be decided by app.data.pipeline.exceedance "
        "(is_pcr_measurement / compute_exceeds_stv / sample_exceeds_stv), never by "
        "comparing a reading to a threshold at the call site. A ddPCR result in "
        "copies/100mL is judged against 1413, not 104:\n  " + "\n  ".join(offenders)
    )


def test_guard_detects_a_planted_violation(tmp_path: Path) -> None:
    """The scan must fail on a real re-derivation, or it proves nothing."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def f(value, stv_threshold):\n"
        "    return value > stv_threshold\n"
    )
    assert _violations(planted, "planted.py"), "guard did not catch a bare > stv_threshold"

    planted.write_text("def f(series):\n    return series.gt(1413)\n")
    assert _violations(planted, "planted.py"), "guard did not catch .gt(1413)"

    planted.write_text("def f(value):\n    return value > 104.0\n")
    assert _violations(planted, "planted.py"), "guard did not catch a bare 104.0 literal"


@pytest.mark.parametrize(
    "source",
    [
        # Equality is not a threshold decision, and neither is a plain count.
        "def f(stv_threshold):\n    return stv_threshold == 104\n",
        "def f(rows):\n    return len(rows) > 3\n",
        "def f(p):\n    return p > 0.7\n",
    ],
)
def test_guard_does_not_fire_on_innocent_code(tmp_path: Path, source: str) -> None:
    planted = tmp_path / "innocent.py"
    planted.write_text(source)
    assert not _violations(planted, "innocent.py")
