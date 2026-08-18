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
narrowest possible reader of a pydantic error: `loc` and `msg`, nothing else.
That is the part a fifth call site cannot forget. `exc.errors()` also carries
the rejected value under `input` and, for a rule that raised, the `ValueError`
object itself under `ctx` - and `details` is serialized into the response body
and logged on the same line, so passing one through posts the caller's own
submission back to them (`.claude/rules/exceptions-security.md`).

There are two entry points because there are two callers, and **which one you
are decides what the first element of `loc` means**. FastAPI puts where the
value came from in front of the path - `("body", "spec", "name")` - and a form
can do nothing with "body". A service validating a model itself gets no such
segment: the first element is already a field name, and a spec whose forbidden
top-level key is literally called `body` reports `loc: ("body",)` about that
key. Deciding by the string would report it against the editor instead, which
is one shape standing in for two - the mistake this module exists to end.
"""

from collections.abc import Sequence

from pydantic_core import ErrorDetails

__all__ = ["field_details", "field_problems", "request_field_problems"]

# Where a validation error came from, as FastAPI reports it in the first element
# of `loc`. Nothing a form can act on, so it is dropped from the path - but only
# for the caller that puts it there. See the module docstring.
_ORIGINS = frozenset({"body", "query", "path", "header", "cookie"})


def _path(location: Sequence[int | str]) -> str:
    """The dotted path a validation error reports, as a form addresses a field.

    List indices stay in it, because "the third capability" is exactly what the
    reader needs to know.
    """
    return ".".join(str(part) for part in location)


def _without_origin(location: Sequence[int | str]) -> Sequence[int | str]:
    return location[1:] if location and location[0] in _ORIGINS else location


def field_problems(errors: Sequence[ErrorDetails], *, root: str) -> list[dict[str, str]]:
    """Pydantic's errors as the `details["fields"]` a form marks its inputs from.

    For a model a service validated itself, where `loc` is the path *within* the
    document rather than within the request. A request body goes through
    :func:`request_field_problems` instead.

    Args:
        errors: What pydantic reported, as `ValidationError.errors()` returns it.
        root: What the caller's document is called on the form that sent it -
            `ingestion_config` for an upload's override, `yaml` for a spec
            somebody is editing by hand, `config` for a capability's settings
            blob. Every path is reported relative to it, which does two things.
            It makes an error naming *no* field addressable: a
            `model_validator(mode="after")` reports `loc: ()`, because the rule
            it broke is about the object rather than any one of its fields, and
            `IngestionConfig` refusing a `chunk_overlap` that does not fit
            inside its `chunk_size` names both in `msg` and neither in `loc`.
            And it makes the two entry points agree - an override refused at
            upload now names exactly what the 422 names when the same pair
            arrives as a collection's own settings, field for field.
    """
    return [
        {"field": ".".join(filter(None, (root, _path(error["loc"])))), "message": error["msg"]}
        for error in errors
    ]


def request_field_problems(errors: Sequence[ErrorDetails]) -> list[dict[str, str]]:
    """The same, for the `RequestValidationError` FastAPI raises about a request.

    There is no root to add - `loc` already names a field of the request body,
    which is the document - but there is one to remove: `loc` starts with where
    the value came from, and a form can do nothing with "body". That segment is
    dropped here and nowhere else, because only this caller puts one there.
    """
    return [
        {"field": _path(_without_origin(error["loc"])) or "request", "message": error["msg"]}
        for error in errors
    ]


def field_details(field: str, message: str, *, root: str = "") -> list[dict[str, str]]:
    """The same shape, for a refusal that names its field without pydantic's help.

    A rule written by hand - a folder id that is not one, a required field left
    empty - knows which field it is about and has no `ValidationError` to read
    it out of. It still answers the *list*, never a singular `details["field"]`:
    a form reads one shape, and that is the plural one (#891).

    Args:
        field: What the form calls the input, relative to `root`.
        message: The refusal, in the words the envelope's `message` carries.
            Duplicated deliberately - an input can only show what is beside it,
            and a toast is beside nothing.
        root: What the caller's document is called on the form that sent it, as
            in :func:`field_problems` - `config` for a connector's settings
            blob. A field of the request body itself has no root.
    """
    return [{"field": ".".join(filter(None, (root, field))), "message": message}]
