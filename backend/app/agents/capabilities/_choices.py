"""What a media tool lets the model choose, stated in the tool's own schema.

A binding names the usual shape, resolution and voice - a default the model may
override per call - and the author bounds what it may override them with: a
highest resolution, a list of allowed voices. The model chooses among exactly
those. Offering them as an `enum` in the parameter's schema, rather than a free
string a docstring describes, is what keeps a value the provider would refuse -
or one the author ruled out - from being sent at all; the tool still refuses one,
for a model that ignores the schema.

A parameter with nothing to choose between is taken out of the schema altogether.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from pydantic_ai.tools import RunContext, ToolDefinition, ToolPrepareFunc

from app.agents.deps import AgentDeps


@dataclass(frozen=True)
class Choice:
    """The values one parameter may take, and what the model reads about each.

    `usual` is what the tool uses when the parameter is left out. It is the
    schema's `default` and named in the description, because "leave it out for
    the usual one" means nothing to a model that cannot see which one that is -
    resolutions are listed shortest first, not usual first. `notes` maps a value
    to a few words appended to the description - a voice's character, which an
    id alone does not say. Values without a note are listed bare.

    `values` of `None` is an open choice - a voice id from the account, which no
    catalog lists: the parameter stays a free string, with the usual one named,
    and the tool checks what it is sent.
    """

    values: tuple[str, ...] | None
    usual: str
    notes: Mapping[str, str | None] | None = None


def offer_choices(schema: Mapping[str, Any], choices: Mapping[str, Choice]) -> dict[str, Any]:
    """`schema` with each named parameter limited to its choice, or removed.

    Args:
        schema: A tool's parameters JSON schema, as Pydantic AI generated it.
        choices: Per parameter name, the values it may take. Fewer than two
            removes the parameter, since there is nothing to choose; `None`
            leaves it open.

    Returns:
        A new schema; `schema` itself is left as it was.
    """
    narrowed: dict[str, Any] = copy.deepcopy(dict(schema))
    properties: dict[str, Any] = narrowed.get("properties", {})
    for name, choice in choices.items():
        if name not in properties:
            raise KeyError(f"The tool has no parameter {name!r} to offer choices for.")
        prop = properties[name]
        if choice.values is None:
            prop["default"] = choice.usual
            prop["description"] = (
                f"{prop.get('description', '')} The usual one is {choice.usual}.".strip()
            )
            continue
        if len(choice.values) < 2:
            del properties[name]
            continue
        if choice.usual not in choice.values:
            raise ValueError(f"{name}: the usual {choice.usual!r} is not one of the values.")
        # `str | None` is generated as an `anyOf` with a `null` default. The enum
        # replaces both: a `null` default outside the enum contradicts it, and a
        # strict transformer reads the parameter as required.
        prop.pop("anyOf", None)
        prop["type"] = "string"
        prop["enum"] = list(choice.values)
        prop["default"] = choice.usual
        notes = [
            f"{value}: {note}"
            for value in choice.values
            if choice.notes and (note := choice.notes.get(value))
        ]
        described = f"{prop.get('description', '')} The usual one is {choice.usual}."
        if notes:
            described += f" Offered: {'; '.join(notes)}."
        prop["description"] = described.strip()
    narrowed["required"] = [name for name in narrowed.get("required", []) if name in properties]
    return narrowed


def schema_for(choices: Mapping[str, Choice]) -> ToolPrepareFunc[AgentDeps]:
    """A `prepare` hook that narrows a tool's schema to `choices`.

    The narrowed schema depends on the binding alone, so it is worked out once,
    from the first definition the hook sees, and handed back unchanged after.
    """
    narrowed: dict[str, Any] | None = None

    async def prepare(ctx: RunContext[AgentDeps], tool_def: ToolDefinition) -> ToolDefinition:
        nonlocal narrowed
        if narrowed is None:
            narrowed = offer_choices(tool_def.parameters_json_schema, choices)
        return replace(tool_def, parameters_json_schema=narrowed)

    return prepare
