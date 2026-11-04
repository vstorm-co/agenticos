"""The late-answer template: which of a WhatsApp account's templates a bot may use (#2076).

Pure functions over Meta's template listing. A usable template is an approved
utility template whose body holds exactly one variable, so the answer (or its
preview) can be its only parameter.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.services.channels.whatsapp_format import utf16_units
from app.services.channels.whatsapp_window import MAX_FIXED_UNITS

_VARIABLE = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_NAME = re.compile(r"[a-z_][a-z0-9_]*")


def _single_variable(body: str) -> re.Match[str] | None:
    """The body's one variable, or `None` when it has none, several, or a malformed one."""
    found = list(_VARIABLE.finditer(body))
    if len(found) != 1 or body.count("{{") != 1 or body.count("}}") != 1:
        return None
    token = found[0].group(1)
    return found[0] if token == "1" or _NAME.fullmatch(token) else None


@dataclass(frozen=True)
class LateTemplate:
    name: str
    language: str
    body: str
    button: str | None = None
    """The template's one quick-reply label: a tap on it asks for the held answer."""

    @property
    def parameter_name(self) -> str | None:
        """The variable's name, or `None` for a positional `{{1}}`."""
        match = _single_variable(self.body)
        token = match.group(1) if match else "1"
        return None if token == "1" else token

    @property
    def fixed_length(self) -> int:
        """UTF-16 units of the body without its variable."""
        match = _single_variable(self.body)
        return utf16_units(
            self.body[: match.start()] + self.body[match.end() :] if match else self.body
        )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _make(
    name: object, language: object, body: object, button: str | None = None
) -> LateTemplate | None:
    name, language, body = _text(name), _text(language), _text(body)
    if name is None or language is None or body is None or _single_variable(body) is None:
        return None
    template = LateTemplate(name=name, language=language, body=body, button=button)
    return template if template.fixed_length <= MAX_FIXED_UNITS else None


def _usable(entry: object) -> LateTemplate | None:
    item = _mapping(entry)
    if item.get("status") != "APPROVED" or item.get("category") != "UTILITY":
        return None
    components = item.get("components")
    if not isinstance(components, list):
        return None
    bodies: list[Mapping[str, Any]] = []
    quick_replies: list[Mapping[str, Any]] = []
    for raw in components:
        component = _mapping(raw)
        kind = component.get("type")
        if kind == "BUTTONS":
            buttons = component.get("buttons")
            quick_replies.extend(
                button
                for raw_button in (buttons if isinstance(buttons, list) else [])
                if (button := _mapping(raw_button)).get("type") == "QUICK_REPLY"
            )
        if kind == "BODY":
            bodies.append(component)
        elif "{{" in repr(component) or (kind == "HEADER" and component.get("format") != "TEXT"):
            return None
    if len(bodies) != 1 or len(quick_replies) > 1:
        return None
    button = _text(quick_replies[0].get("text")) if quick_replies else None
    return _make(item.get("name"), item.get("language"), bodies[0].get("text"), button)


def usable_templates(listing: Sequence[object]) -> list[LateTemplate]:
    """The listing's usable templates; a malformed entry is skipped, never raised on."""
    return [template for entry in listing if (template := _usable(entry)) is not None]


def stored_template(value: object) -> LateTemplate | None:
    """The bot's stored template, checked again; anything malformed reads as no template."""
    item = _mapping(value)
    return _make(
        item.get("name"), item.get("language"), item.get("body"), _text(item.get("button"))
    )


def to_stored(template: LateTemplate) -> dict[str, str]:
    stored = {"name": template.name, "language": template.language, "body": template.body}
    if template.button is not None:
        stored["button"] = template.button
    return stored
