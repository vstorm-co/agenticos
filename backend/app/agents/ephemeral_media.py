"""Pictures a run shows its model and nobody keeps.

A desktop screenshot is the model's working view of a screen that may hold
anything - a password manager left open, another customer's record. The model
needs it for its next step and nobody needs it afterwards, so it is marked when
it is made and replaced with a sentence wherever a run's messages are written
down: the state an approval parks, a parked delegate's history, the run's
manifest and a compacted conversation. A resumed run is shown the sentence, and
the next screenshot it takes is a fresh one.

Marked rather than every picture stripped: an attachment a person sent is theirs
and is kept, and a run parked on an approval has to resume with it.
"""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from pydantic_ai.messages import BinaryContent, ModelMessage, ModelMessagesTypeAdapter

EPHEMERAL = "ephemeral-"
"""The prefix of an ephemeral picture's `identifier`, which survives serialization."""

NOT_KEPT = "[A screenshot the model was shown at the time. It is not kept.]"


def ephemeral_image(data: bytes, media_type: str) -> BinaryContent:
    """A picture for the model that is dropped from every stored copy of the run."""
    return BinaryContent(data=data, media_type=media_type, identifier=f"{EPHEMERAL}{uuid4().hex}")


def _ephemeral(value: object) -> bool:
    if isinstance(value, BinaryContent):
        return value.identifier.startswith(EPHEMERAL)
    if isinstance(value, dict):
        identifier = value.get("identifier")
        return (
            value.get("kind") == "binary"
            and isinstance(identifier, str)
            and identifier.startswith(EPHEMERAL)
        )
    return False


def without_ephemeral(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialized messages with every ephemeral picture replaced by `NOT_KEPT`, in place.

    A picture reaches a message as a part's content or one item of it - a user
    prompt's, or a tool's return - so that is the depth walked.
    """
    for message in messages:
        for part in message.get("parts", []):
            content = part.get("content")
            if isinstance(content, list):
                part["content"] = [NOT_KEPT if _ephemeral(item) else item for item in content]
            elif _ephemeral(content):
                part["content"] = NOT_KEPT
    return messages


def dump_messages(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    """Messages as JSON to store, without the pictures nobody keeps."""
    return without_ephemeral(ModelMessagesTypeAdapter.dump_python(list(messages), mode="json"))


def describe_binary(value: object) -> str:
    """What a stored text says in place of a picture: never its bytes.

    For `json.dumps(default=...)`, which reaches here for anything it cannot
    write; everything that is not a picture keeps its `str`.
    """
    if isinstance(value, BinaryContent):
        return NOT_KEPT if _ephemeral(value) else f"[{value.media_type}]"
    return str(value)
