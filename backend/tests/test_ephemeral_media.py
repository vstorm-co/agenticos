"""Pictures a run shows its model and nobody keeps.

A desktop screenshot can hold anything on that screen. What matters is that no
stored copy of a run - the state an approval parks, the manifest, a compacted
history, a transcript row - carries its bytes, and that a person's own
attachment is left alone.
"""

import json

import pytest
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ToolReturnPart,
    UserPromptPart,
)

from app.agents.ephemeral_media import (
    NOT_KEPT,
    describe_binary,
    dump_messages,
    ephemeral_image,
    without_ephemeral,
)
from app.services.transcript import tool_result_text

_SECRET_SCREEN = b"\xff\xd8 a password manager, open"


def _history() -> list[ModelMessage]:
    attachment = BinaryContent(data=b"a person's photo", media_type="image/png")
    return [
        ModelRequest(parts=[UserPromptPart(content=["Look at this", attachment])]),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="computer_screenshot",
                    content=["Desktop.", ephemeral_image(_SECRET_SCREEN, "image/jpeg")],
                    metadata={"kept": True},
                ),
                ToolReturnPart(
                    tool_name="bare", content=ephemeral_image(_SECRET_SCREEN, "image/jpeg")
                ),
                ToolReturnPart(tool_name="plain", content="text"),
            ]
        ),
    ]


@pytest.mark.security
def test_a_stored_run_keeps_no_screenshot_and_every_attachment():
    stored = dump_messages(_history())
    encoded = json.dumps(stored)

    assert "password" not in encoded
    assert "cGFzc3dvcmQ" not in encoded  # nor in base64
    assert stored[1]["parts"][0]["content"] == ["Desktop.", NOT_KEPT]
    assert stored[1]["parts"][0]["metadata"] == {"kept": True}
    assert stored[1]["parts"][1]["content"] == NOT_KEPT
    assert stored[1]["parts"][2]["content"] == "text"
    # The person's own picture is theirs, and a resumed run needs it.
    restored = ModelMessagesTypeAdapter.validate_python(stored)
    first = restored[0].parts[0]
    assert isinstance(first, UserPromptPart)
    assert isinstance(first.content[1], BinaryContent)


def test_a_delegates_history_read_back_as_json_is_stripped_the_same_way():
    raw = ModelMessagesTypeAdapter.dump_json(_history())
    stored = without_ephemeral(json.loads(raw))
    assert "password" not in json.dumps(stored)


@pytest.mark.security
def test_a_transcript_row_never_holds_a_pictures_bytes():
    """A tool row is text a person reads, and `str(BinaryContent)` is its bytes."""
    attachment = BinaryContent(data=b"a person's photo", media_type="image/png")
    text = tool_result_text(["Desktop.", ephemeral_image(_SECRET_SCREEN, "image/jpeg"), attachment])

    assert json.loads(text) == ["Desktop.", NOT_KEPT, "[image/png]"]
    assert describe_binary(1.5) == "1.5"
