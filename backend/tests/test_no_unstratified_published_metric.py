"""Guard: no published metric is computed without its assay pair (E3).

``exceeds_stv`` pools two labelling universes. Culture rows sit at a base rate
of ~0.10 against the 104 MPN/CFU marine STV; San Diego ddPCR rows at ~0.59
against the 1413-copies BAV. ddPCR is 15% of the 1095d window's rows and 52% of
its positive labels. A metric averaged over that mixture describes no
population, and — because AUCPR is base-rate dependent — it *moves* whenever the
assay mix moves, at perfectly constant skill.

The fix is :mod:`app.ml.assay_strata` plus ``training._scored``, which is
``classification_metrics`` with ``by_assay`` attached. The failure mode this
file exists to prevent is a new publication site quietly calling
``classification_metrics`` directly: nothing would break, no test would fail,
and one more pooled figure would ship looking exactly like the stratified ones.

So this is an AST scan, not a convention. It parses ``app/ml/training.py`` and
fails on any ``classification_metrics(...)`` call outside the small, explicitly
listed set of places where a pooled figure is legitimate.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TRAINING = Path(__file__).resolve().parents[1] / "app" / "ml" / "training.py"

# Functions allowed to call classification_metrics directly, and why.
_ALLOWED_SCOPES: dict[str, str] = {
    # `_scored` IS the stratifying wrapper — it must call the raw metric.
    "_scored": "the wrapper itself",
    # Fixture-only development path (`--sample-fixture`). It never writes
    # system_health.json from curated data, and the fixture frame has no assay.
    "train_baselines": "fixture-only dev path, no assay in the frame",
    # Torch sequence models. On the curated path they are only reachable through
    # `_spatial_holdout_metrics`, which stratifies the pooled result itself.
    "train_sequence_model": "research path; curated use routes via _spatial_holdout_metrics",
    # Computes the pooled figure and then immediately calls
    # attach_stratified_metrics on it — asserted separately below.
    "_spatial_holdout_metrics": "pools, then attaches by_assay in the same function",
}


def _enclosing_function(tree: ast.Module) -> dict[int, str]:
    """Map every line number to the name of the *outermost* function holding it.

    Outermost, not innermost: `_record_valid_metrics` is a closure inside
    `_run_winner_only`, and an exemption keyed on the closure name would let a
    caller re-introduce a pooled published metric just by nesting it.
    """
    owner: dict[int, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner[line] = node.name
    return owner


def _direct_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "classification_metrics"
    ]


def test_every_classification_metrics_call_is_in_an_allowed_scope() -> None:
    tree = ast.parse(TRAINING.read_text())
    owner = _enclosing_function(tree)

    violations = [
        f"app/ml/training.py:{call.lineno} inside "
        f"{owner.get(call.lineno, '<module scope>')}()"
        for call in _direct_calls(tree)
        if owner.get(call.lineno) not in _ALLOWED_SCOPES
    ]

    assert not violations, (
        "classification_metrics called outside an allowed scope — use `_scored` "
        "(or attach_stratified_metrics) so the figure ships with its "
        "culture/ddPCR pair:\n  " + "\n  ".join(violations)
    )


def test_the_spatial_pooler_attaches_its_pair_in_the_same_function() -> None:
    """`_spatial_holdout_metrics` is exempted only because it stratifies inline.
    If that call is ever removed the exemption becomes a hole."""
    tree = ast.parse(TRAINING.read_text())
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_spatial_holdout_metrics"
    )
    attaches = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "attach_stratified_metrics"
    ]
    assert attaches, (
        "_spatial_holdout_metrics no longer attaches by_assay — remove its "
        "exemption from _ALLOWED_SCOPES or restore the call"
    )


def test_guard_detects_a_planted_violation(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def _publish_a_new_metric(labels, probs):\n"
        "    return classification_metrics(labels, probs)\n"
    )
    tree = ast.parse(planted.read_text())
    owner = _enclosing_function(tree)
    calls = _direct_calls(tree)
    assert calls
    assert owner[calls[0].lineno] == "_publish_a_new_metric"
    assert owner[calls[0].lineno] not in _ALLOWED_SCOPES


@pytest.mark.parametrize(
    "source",
    [
        "def f(y, p):\n    return _scored(y, p, assay)\n",
        "def f(y, p):\n    m = _scored_eval(y, p)\n    return m\n",
        "import classification_metrics_helpers\n",
    ],
)
def test_guard_does_not_fire_on_innocent_code(tmp_path: Path, source: str) -> None:
    planted = tmp_path / "innocent.py"
    planted.write_text(source)
    assert not _direct_calls(ast.parse(planted.read_text()))
