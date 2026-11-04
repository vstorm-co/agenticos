"""Request-only reference parts kept out of retained run snapshots."""

from dataclasses import dataclass, replace

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart


@dataclass
class ChannelReferencePart(UserPromptPart):
    """Platform reference data for model dispatch, not a stored user message."""


def recorded_channel_messages(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Retain the original message parts, omitting personal channel references."""
    recorded: list[ModelMessage] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            parts = [part for part in message.parts if not isinstance(part, ChannelReferencePart)]
            if len(parts) != len(message.parts):
                recorded.append(replace(message, parts=parts))
                continue
        recorded.append(message)
    return recorded
