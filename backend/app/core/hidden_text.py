"""Characters a proposed or edited text may not carry, because a person cannot see them.

A control character other than a newline or a tab, a bidirectional embedding, override
or isolate, and a Unicode tag character draw nothing or reorder the text around them.
Text holding one reads one way to the person who accepts it and another way to the
model that reads it afterwards, so such text is refused wherever it would become an
agent's instructions, a tool's description, a skill or a context file. Zero-width
characters are let through: the console writes each one out where it shows the text.
"""

import unicodedata

_ALLOWED_CONTROLS = frozenset("\n\t")
_BIDI = frozenset(chr(point) for point in (*range(0x202A, 0x202F), *range(0x2066, 0x206A)))
_TAGS = range(0xE0000, 0xE0080)


def _refused(char: str) -> bool:
    if char in _ALLOWED_CONTROLS:
        return False
    return unicodedata.category(char) == "Cc" or char in _BIDI or ord(char) in _TAGS


def refused_characters(text: str) -> list[str]:
    """The characters of `text` it may not carry, as `U+XXXX`, in order and once each."""
    found = dict.fromkeys(f"U+{ord(char):04X}" for char in text if _refused(char))
    return list(found)


def visible(text: str) -> str:
    """`text` unchanged, or a `ValueError` naming the characters it may not carry.

    For a Pydantic `AfterValidator`, so a refusal names the field that holds them.
    """
    if refused := refused_characters(text):
        raise ValueError("This text holds characters that cannot be seen: " + ", ".join(refused))
    return text


def holds_refused(value: object) -> bool:
    """Whether a text, or any text inside a JSON value, carries a refused character."""
    if isinstance(value, str):
        return bool(refused_characters(value))
    if isinstance(value, dict):
        return any(holds_refused(key) or holds_refused(item) for key, item in value.items())
    if isinstance(value, list):
        return any(holds_refused(item) for item in value)
    return False
