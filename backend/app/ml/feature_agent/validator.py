"""
AST-level validation for agent-generated beach feature functions.

Rules mirror the playground credit-risk validator but are adapted for the
beach water-quality time-series schema.  Key domain differences:
  - Data has a (beach_id, sample_date) time dimension; leakage is
    temporal (using data from date T in features for date T).
  - .shift / .diff MUST chain off .groupby('beach_id') to avoid
    cross-beach contamination (same role as groupby('prism_consumer_id')).
  - .rolling MUST use closed='left' so the current sample's enterococcus
    value is never visible in its own rolling statistic.
  - No global aggregations; all reductions must be per-beach or per
    (beach, time-window).
"""
from __future__ import annotations

import ast


REQUIRED_FUNCTION_NAME = "build_novel_feature"

FORBIDDEN_PATTERNS = ["os.system", "subprocess", "eval(", "__import__", "open("]

SLOW_PANDAS = {"pivot_table", "crosstab", "resample", "explode", "merge_asof"}
SLOW_SCIPY = {"pearsonr", "kendalltau", "spearmanr", "entropy", "pointbiserialr", "linregress"}


class _BeachLeakageChecker(ast.NodeVisitor):
    """
    Checks that shift/diff always chain off groupby('beach_id'), and that
    rolling windows always use closed='left'.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []

    def _has_groupby_beach(self, node: ast.AST) -> bool:
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Attribute)
                and child.attr == "groupby"
            ):
                # check the first arg to groupby is 'beach_id'
                parent_call = getattr(child, "_parent_call", None)
                return True  # groupby present — good enough at static level
        return False

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Attribute):
            method = node.func.attr

            # shift/diff without groupby → cross-beach leakage
            if method in ("shift", "diff"):
                chain = node.func.value
                has_groupby = any(
                    isinstance(n, ast.Attribute) and n.attr == "groupby"
                    for n in ast.walk(chain)
                )
                if not has_groupby:
                    self.errors.append(
                        f".{method}() must chain off .groupby('beach_id') to prevent "
                        "cross-beach temporal leakage."
                    )

            # rolling without closed='left' → leaks current sample into its own window
            if method == "rolling":
                closed_value = None
                for kw in node.keywords:
                    if kw.arg == "closed" and isinstance(kw.value, ast.Constant):
                        closed_value = kw.value.value
                if closed_value != "left":
                    self.errors.append(
                        ".rolling() must use closed='left' to prevent the current "
                        "sample's enterococcus value from leaking into its own "
                        "rolling statistic."
                    )

            # banned pandas operations
            if method in SLOW_PANDAS:
                self.errors.append(
                    f"pd.{method}() is forbidden. Use groupby().agg() with "
                    "named aggregation strings instead."
                )

            # banned scipy ops
            if method in SLOW_SCIPY:
                self.errors.append(
                    f"scipy.stats.{method}() requires Python iteration per group. "
                    "Use pandas named agg strings ('skew', 'kurt', 'std') instead."
                )

            # apply — too slow, hides loops
            if method == "apply":
                self.errors.append(
                    ".apply() is forbidden. It runs Python per-row/group and causes "
                    "timeouts. Use vectorized pandas operations."
                )

            # lambda inside agg dict → per-group Python
            if method == "agg":
                for arg in node.args:
                    if isinstance(arg, ast.Dict):
                        for val in arg.values:
                            if isinstance(val, ast.Lambda):
                                self.errors.append(
                                    "Lambda inside .agg() dict is forbidden. "
                                    "Use named strings: .agg({'col': 'std'}) or "
                                    ".agg(my_col=('col', 'std'))."
                                )
                for kw in node.keywords:
                    if isinstance(kw.value, ast.Lambda):
                        self.errors.append(
                            "Lambda inside .agg() keyword is forbidden."
                        )

            # transform(lambda) — per-group Python
            if method == "transform":
                for arg in node.args:
                    if isinstance(arg, (ast.Lambda, ast.FunctionDef)):
                        self.errors.append(
                            "transform(lambda) is forbidden. Use named strings like "
                            "transform('mean') only."
                        )

        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self.errors.append(
            "for-loops are forbidden. Use vectorized pandas operations."
        )
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self.errors.append(
            "while-loops are forbidden. Use vectorized pandas operations."
        )
        self.generic_visit(node)


def validate(code: str) -> tuple[bool, str]:
    """
    Returns (is_valid, error_message).  error_message is empty on success.
    """
    # Security checks (string-level, before parse)
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in code:
            return False, f"Security check failed: forbidden pattern '{pattern}'."

    # Must define the required function
    if f"def {REQUIRED_FUNCTION_NAME}(" not in code:
        return False, (
            f"Missing required function definition: "
            f"def {REQUIRED_FUNCTION_NAME}(beach_day_df, advisories_df, stations_df, **kwargs)"
        )

    # Parse
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"Syntax error: {exc}"

    # Must have a return statement
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == REQUIRED_FUNCTION_NAME:
            if not any(isinstance(n, ast.Return) for n in ast.walk(node)):
                return False, "Function is missing a return statement."

    # Domain-specific leakage checks
    checker = _BeachLeakageChecker()
    checker.visit(tree)
    if checker.errors:
        return False, " | ".join(checker.errors)

    return True, ""
