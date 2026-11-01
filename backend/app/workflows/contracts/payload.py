"""Byte bounds for inline JSON; larger workflow data travels as file references."""

import json

from pydantic import BaseModel
from pydantic_core import to_jsonable_python


class PayloadTooLarge(ValueError):
    """The encoded payload exceeds its caller's byte budget."""


def _json_boundary_value(value: object) -> object:
    if isinstance(value, BaseModel):
        # A shallow projection keeps repeated nested values shared until the
        # encoder reaches them; model_dump would copy the entire tree first.
        return {name: getattr(value, name) for name in type(value).model_fields}
    return to_jsonable_python(value)


def json_byte_size(value: object, *, limit: int) -> int:
    """Measure JSON incrementally; model fields are a conservative preflight projection."""
    size = 0
    for part in json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, separators=(",", ":"), default=_json_boundary_value
    ).iterencode(value):
        # UTF-8 needs at least one byte per character; avoid encoding a huge chunk.
        if len(part) > limit - size:
            raise PayloadTooLarge("Inline JSON exceeds its byte limit")
        size += len(part.encode("utf-8"))
        if size > limit:
            raise PayloadTooLarge("Inline JSON exceeds its byte limit")
    return size
