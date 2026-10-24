"""Byte bounds for inline JSON; larger workflow data travels as file references."""

import json


class PayloadTooLarge(ValueError):
    """The encoded payload exceeds its caller's byte budget."""


def json_byte_size(value: object, *, limit: int) -> int:
    """Measure compact UTF-8 JSON incrementally, stopping at the budget."""
    size = 0
    for part in json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).iterencode(value):
        # UTF-8 needs at least one byte per character; avoid encoding a huge chunk.
        if len(part) > limit - size:
            raise PayloadTooLarge("Inline JSON exceeds its byte limit")
        size += len(part.encode("utf-8"))
        if size > limit:
            raise PayloadTooLarge("Inline JSON exceeds its byte limit")
    return size
