"""Lossless bounded skill-file bodies shared by storage and transport boundaries."""

import base64
import binascii
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import JsonValue, StringConstraints, TypeAdapter

_METADATA = TypeAdapter(dict[str, JsonValue])

ResourceEncoding = Literal["utf8", "base64"]
type SkillMarkdown = Annotated[str, StringConstraints(strip_whitespace=False)]
MAX_SKILL_FILE_BYTES = 8 * 1024 * 1024
MAX_SKILL_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_SKILL_PACKAGE_FILES = 1024
MAX_ENCODED_SKILL_FILE_CHARS = 4 * ((MAX_SKILL_FILE_BYTES + 2) // 3)


@dataclass(frozen=True, slots=True)
class EncodedSkillFile:
    content: str
    encoding: ResourceEncoding


def decode_skill_file(content: str, encoding: ResourceEncoding = "utf8") -> bytes:
    """Decode a canonical payload, refusing invalid or oversized bodies before storage."""
    if encoding == "utf8":
        if "\0" in content:
            raise ValueError("A file containing NUL bytes must use base64 encoding")
        raw = content.encode("utf-8")
    else:
        if len(content) > MAX_ENCODED_SKILL_FILE_CHARS:
            raise ValueError("A skill file exceeds the 8 MiB limit")
        try:
            raw = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("A binary skill file needs canonical base64 content") from exc
        if base64.b64encode(raw).decode("ascii") != content:
            raise ValueError("A binary skill file needs canonical base64 content")
    if len(raw) > MAX_SKILL_FILE_BYTES:
        raise ValueError("A skill file exceeds the 8 MiB limit")
    return raw


def encode_skill_file(raw: bytes) -> EncodedSkillFile:
    """Use exact UTF-8 when JSONB/PostgreSQL can hold it, otherwise canonical base64.

    Encoding is deterministic for each byte sequence, so content-addressed versions
    cannot disagree about a shared body. Existing text hashes remain unchanged.
    """
    if len(raw) > MAX_SKILL_FILE_BYTES:
        raise ValueError("A skill file exceeds the 8 MiB limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None and "\0" not in text:
        return EncodedSkillFile(text, "utf8")
    return EncodedSkillFile(base64.b64encode(raw).decode("ascii"), "base64")


def validate_skill_metadata(value: object) -> dict[str, JsonValue]:
    """Validate bounded inert frontmatter without YAML objects, cycles or non-JSON values."""
    remaining = 4096
    ancestors: set[int] = set()

    def inspect(item: object, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 12:
            raise ValueError("Skill metadata exceeds the nesting or value-count limit")
        if item is None or isinstance(item, bool | int):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Skill metadata numbers must be finite")
            return
        if isinstance(item, str):
            if "\0" in item:
                raise ValueError("Skill metadata cannot contain NUL bytes")
            return
        if isinstance(item, dict | list):
            identity = id(item)
            if identity in ancestors:
                raise ValueError("Skill metadata cannot contain reference cycles")
            ancestors.add(identity)
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str) or "\0" in key:
                        raise ValueError("Skill metadata keys must be text without NUL bytes")
                    inspect(child, depth + 1)
            else:
                for child in item:
                    inspect(child, depth + 1)
            ancestors.remove(identity)
            return
        raise ValueError("Skill metadata accepts JSON values only")

    if not isinstance(value, dict):
        raise ValueError("Skill metadata must be an object")  # noqa: TRY004 - Pydantic validators report ValueError as invalid input.
    if {"name", "description"}.intersection(value):
        raise ValueError("Name and description belong in the skill's own fields")
    inspect(value, 0)
    parsed = _METADATA.validate_python(value)
    if len(json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode()) > 64 * 1024:
        raise ValueError("Skill metadata exceeds the 64 KiB limit")
    return parsed


def same_skill_metadata(left: Mapping[str, JsonValue], right: Mapping[str, JsonValue]) -> bool:
    """JSON identity keeps booleans distinct from numbers and ignores object key order."""
    return json.dumps(dict(left), sort_keys=True, separators=(",", ":")) == json.dumps(
        dict(right), sort_keys=True, separators=(",", ":")
    )
