"""What a media tool offers the model: the author's choices as an enum, an open
choice with its usual value named, or nothing.

`offer_choices` rewrites a tool's generated schema, and a schema is prompt - so
these pin that a choice narrows a parameter rather than describing it, that a
parameter with nothing to choose leaves the schema whole, and that the original
is never edited in place, since Pydantic AI keeps it on the tool.
"""

from typing import Any
from uuid import uuid4

import pytest
from pydantic_ai._run_context import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage

from app.agents.capabilities._choices import Choice, offer_choices, schema_for
from app.agents.deps import AgentDeps

pytestmark = pytest.mark.anyio


def _schema() -> dict[str, Any]:
    return {
        "additionalProperties": False,
        "properties": {
            "text": {"type": "string", "description": "The words."},
            "voice": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Who speaks.",
            },
            "style": {"type": "string", "description": "How."},
        },
        "required": ["text", "style"],
        "type": "object",
    }


def test_two_or_more_values_become_the_parameters_enum():
    narrowed = offer_choices(_schema(), {"voice": Choice(("marin", "cedar"), usual="cedar")})

    voice = narrowed["properties"]["voice"]
    assert voice["enum"] == ["marin", "cedar"]
    assert voice["type"] == "string" and "anyOf" not in voice
    # Still optional - left out is how the usual voice is asked for - and the
    # schema says which that is, rather than a `null` outside its own enum.
    assert voice["default"] == "cedar" and "voice" not in narrowed["required"]
    assert voice["description"] == "Who speaks. The usual one is cedar."


def test_a_single_value_takes_the_parameter_out_of_the_schema():
    narrowed = offer_choices(
        _schema(), {"style": Choice(("calm",), usual="calm"), "voice": Choice((), usual="")}
    )

    assert set(narrowed["properties"]) == {"text"}
    assert narrowed["required"] == ["text"]


def test_notes_say_what_each_value_is_and_values_without_one_are_left_bare():
    narrowed = offer_choices(
        _schema(),
        {
            "voice": Choice(
                ("abc123", "def456", "ghi789"),
                usual="def456",
                notes={"abc123": "Anna, narrator", "def456": None},
            )
        },
    )

    assert narrowed["properties"]["voice"]["description"] == (
        "Who speaks. The usual one is def456. Offered: abc123: Anna, narrator."
    )


def test_the_schema_it_was_given_is_left_as_it_was():
    original = _schema()

    offer_choices(original, {"voice": Choice(("a", "b"), usual="a"), "style": Choice((), usual="")})

    assert original == _schema()


def test_an_open_choice_keeps_the_parameter_and_names_the_usual_value():
    narrowed = offer_choices(_schema(), {"voice": Choice(None, usual="abc123")})

    voice = narrowed["properties"]["voice"]
    assert "enum" not in voice and voice["default"] == "abc123"
    assert voice["description"] == "Who speaks. The usual one is abc123."


def test_a_usual_value_outside_the_values_is_a_mistake_said_at_once():
    with pytest.raises(ValueError, match="the usual 'c' is not one of the values"):
        offer_choices(_schema(), {"voice": Choice(("a", "b"), usual="c")})


def test_a_parameter_the_tool_does_not_have_is_a_mistake_said_at_once():
    with pytest.raises(KeyError, match="no parameter 'speaker'"):
        offer_choices(_schema(), {"speaker": Choice(("a", "b"), usual="a")})


async def test_the_prepare_hook_narrows_once_and_hands_the_same_schema_back():
    prepare = schema_for({"voice": Choice(("a", "b"), usual="a")})
    ctx = RunContext(deps=AgentDeps(organization_id=uuid4()), model=TestModel(), usage=RunUsage())
    tool_def = ToolDefinition(name="generate_speech", parameters_json_schema=_schema())

    first = await prepare(ctx, tool_def)
    second = await prepare(ctx, tool_def)

    assert first is not None and second is not None
    assert first.parameters_json_schema["properties"]["voice"]["enum"] == ["a", "b"]
    assert second.parameters_json_schema is first.parameters_json_schema
    assert tool_def.parameters_json_schema == _schema()
