"""The expression language `data.map` and `logic.if` share: JMESPath, not eval.

A graph is configuration an organization writes, so nothing in it may execute
code: no `eval`, no JavaScript, no template language with loops. JMESPath is a
declarative JSON query language - selections, projections, comparisons and a
fixed set of functions - with no assignment, no loops and no user-defined
functions. It is further narrowed here to the functions in `ALLOWED_FUNCTIONS`,
checked by walking the parsed expression, so what an expression may do is this
module's list rather than whatever a later JMESPath release adds.

An expression is checked when the config is validated - at publish and at every
draft-time validation - so a malformed one or a refused function is a
`GraphValidationError`, never a runtime failure. Evaluation itself cannot raise
for a well-formed expression except on a type mismatch inside a function
(`length(42)`), which `evaluate` reports as `ExpressionError`.
"""

from __future__ import annotations

from typing import Any

import jmespath
from jmespath import exceptions as jmespath_errors

MAX_EXPRESSION_LENGTH = 1000
"""The longest expression a node accepts: long enough for any honest selection."""

ALLOWED_FUNCTIONS = frozenset(
    {
        "abs",
        "avg",
        "ceil",
        "contains",
        "ends_with",
        "floor",
        "join",
        "keys",
        "length",
        "max",
        "merge",
        "min",
        "not_null",
        "reverse",
        "sort",
        "starts_with",
        "sum",
        "to_array",
        "to_number",
        "to_string",
        "type",
        "values",
    }
)
"""Pure functions over the value at hand. `map`, `sort_by`, `max_by` and `min_by`
take an expression reference and are left out: nothing a node needs, and the
one way to make an expression's cost depend on nested evaluation."""


class ExpressionError(ValueError):
    """An expression that does not parse, calls a refused function, or fails on its data."""


def check(expression: str) -> str:
    """Return `expression` unchanged if it may be used, or raise `ExpressionError`.

    For a `field_validator`: a Pydantic `ValueError` becomes a field-scoped
    problem in the graph's validation report.
    """
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(
            f"An expression may be at most {MAX_EXPRESSION_LENGTH} characters long"
        )
    try:
        parsed = jmespath.compile(expression).parsed
    except jmespath_errors.JMESPathError as exc:
        raise ExpressionError(
            f"This expression does not parse: {str(exc).splitlines()[0]}"
        ) from exc
    refused = sorted(_function_names(parsed) - ALLOWED_FUNCTIONS)
    if refused:
        raise ExpressionError(f"These functions are not allowed here: {', '.join(refused)}")
    return expression


def evaluate(expression: str, data: Any) -> Any:
    """Evaluate a checked `expression` against JSON-shaped `data`.

    Raises:
        ExpressionError: A function was handed a value of the wrong type.
    """
    try:
        return jmespath.search(check(expression), data)
    except jmespath_errors.JMESPathError as exc:
        raise ExpressionError(f"This expression could not be evaluated: {exc}") from exc


def truthy(value: Any) -> bool:
    """JMESPath's own truthiness: false for null, false, and an empty string, list or object.

    Checked by identity and type rather than `value in (...)`: in Python `0 == False`,
    and JMESPath counts zero as true.
    """
    if value is None or value is False:
        return False
    return not (isinstance(value, str | list | dict) and not value)


def _function_names(node: dict[str, Any]) -> set[str]:
    """Every function an expression's parsed tree calls, at any depth."""
    names: set[str] = set()
    if node.get("type") == "function_expression":
        names.add(str(node.get("value")))
    for child in node.get("children", ()):
        names |= _function_names(child)
    return names
