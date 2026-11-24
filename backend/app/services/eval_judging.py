"""Judge an answer against an expectation.

Shared by workflow evals and the failure-learning loop: both write cases as
an expectation and judge an answer against it with plain string matching.
The gate is a floor, not a proof - a model can satisfy `contains` without
fixing the behaviour, and `not_contains` by saying nothing at all.
"""

import json
from typing import Any

from app.schemas.eval_judging import EvalExpectation

_SHOWN = 500
"""How much of an answer a result shows: enough to see what it said."""


def _at(output: dict[str, Any], field: str | None) -> Any:
    """The value at a dotted path into a step's output, or `None` past its end."""
    if field is None:
        return output
    value: Any = output
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def judge(expectation: EvalExpectation, output: dict[str, Any]) -> tuple[bool, str]:
    """Whether `output` says what `expectation` asks, and what it said there."""
    value = _at(output, expectation.field)
    actual = "" if value is None else _as_text(value)
    said, wanted = actual.strip().casefold(), expectation.value.strip().casefold()
    if expectation.kind == "equals":
        passed = said == wanted
    elif expectation.kind == "contains":
        passed = wanted in said
    else:
        passed = wanted not in said
    return passed, actual[:_SHOWN]
