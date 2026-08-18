"""What a refusal says about the field it refuses, in the one shape a form reads.

A per-field refusal is only worth raising if the form can mark the input it
names, and that takes **one** shape on the wire. There were two.
:func:`app.api.exception_handlers.validation_exception_handler` answered
`details={"fields": [{"field": ..., "message": ...}]}`, which
`frontend/src/lib/api-error.ts` reads; four services handed pydantic's own
`exc.errors()` through untouched under `details={"errors": [...]}`, which it
reads nowhere. So a refused ingestion override, a refused spec import and a
refused capability config each delivered a sentence to a toast and marked
nothing - the half of the answer that says *which box to fix*, missing from the
three refusals written to provide it (#882).

This module is the only place that shape is built, and it is deliberately the
narrowest possible reader of a pydantic error: `loc` and `msg`, nothing
else. That is the part a fifth call site cannot forget. `exc.errors()` also
carries the rejected value under `input` and, for a rule that raised, the
`ValueError` object itself under `ctx` - and `details` is serialized into
the response body and logged on the same line, so passing one through posts the
caller's own submission back to them (`.claude/rules/exceptions-security.md`).
"""

from collections.abc import Sequence

from pydantic_core import ErrorDetails

__all__ = ["field_problems"]

# Where a validation error came from, as pydantic reports it in the first
# element of `loc`. Nothing a form can act on, so it is dropped from the path.
_LOCATIONS = frozenset({"body", "query", "path", "header", "cookie"})


def _path(location: Sequence[int | str], root: str) -> str:
    """The dotted path of the field one validation error is about.

    Pydantic reports where the value came from as well as where it sits -
    `("body", "spec", "name")`. A form can do nothing with "body", so it is
    dropped and the rest joined: `spec.name`. List indices stay in the path,
    because "the third capability" is exactly what the reader needs to know.
    """
    parts = list(location)
    if parts and parts[0] in _LOCATIONS:
        parts = parts[1:]
    return ".".join(str(part) for part in parts) or root


def field_problems(errors: Sequence[ErrorDetails], *, root: str) -> list[dict[str, str]]:
    """Pydantic's errors as the `details["fields"]` a form marks its inputs from.

    Args:
        errors: What pydantic reported, as `ValidationError.errors()` returns it.
        root: The field an error that names none belongs to. A
            `model_validator(mode="after")` reports `loc: ()`, because the rule
            it broke is about the object rather than any one of its fields -
            `IngestionConfig` refusing a `chunk_overlap` that does not fit
            inside its `chunk_size` names both in `msg` and neither in `loc`. A
            form still has to be told where to put that sentence, so the raiser
            names the field the whole document belongs to: `ingestion_config`
            for an upload's override - the same field the 422 names when that
            pair arrives as a collection's own settings - and `yaml` for a spec
            somebody is editing by hand.
    """
    return [{"field": _path(error["loc"], root), "message": error["msg"]} for error in errors]
