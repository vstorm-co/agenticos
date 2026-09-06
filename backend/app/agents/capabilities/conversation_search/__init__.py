"""Conversation search - find and read what was said in past conversations."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.conversation_search._capability import ConversationSearch

__all__ = [
    "CONVERSATION_SEARCH_CAPABILITY_ID",
    "ConversationSearch",
    "ConversationSearchConfig",
]

CONVERSATION_SEARCH_CAPABILITY_ID = "conversation_search"


class ConversationSearchConfig(BaseModel):
    """How much a search brings back.

    One field, because there is only one genuine choice here. *Whose*
    conversations are searchable is not configurable - it is the person the run is
    answering, resolved server-side - and an operator who does not want agents
    reading conversations at all takes the `conversations:read` scope away rather
    than reconfiguring every agent.
    """

    max_results: int = Field(
        default=10,
        ge=1,
        le=25,
        description=(
            "How many conversations one search returns at most. Each brings back a "
            "short passage, so a high number costs context on every search."
        ),
    )


@register(
    id=CONVERSATION_SEARCH_CAPABILITY_ID,
    name="Conversation search",
    category="knowledge",
    description=(
        "Let the agent search what was said in past conversations and open one in "
        "full. The corpus is the conversations of the person it is talking to - "
        "their own, the ones shared with them, and the group chats they are still "
        "in - never anybody else's. It is off in group chats, where an answer is "
        "read by the whole channel."
    ),
    tools=(
        CapabilityToolInfo(
            id="search_conversations",
            description=(
                "Search this person's past conversations for what was actually said in them."
            ),
        ),
        CapabilityToolInfo(
            id="read_conversation",
            description=("Read a past conversation in full, turn by turn, once you have found it."),
        ),
    ),
    scopes=("conversations:read",),
    config_schema=ConversationSearchConfig,
)
def _build(ctx: CapabilityBuildContext) -> ConversationSearch:
    """Build the capability from a binding's config.

    Never `None`: there is no configuration that leaves it with nothing to do. An
    agent that should not read past conversations does not bind it, and a
    deployment that allows none of them withholds `conversations:read`.
    """
    config = (
        ctx.config
        if isinstance(ctx.config, ConversationSearchConfig)
        else ConversationSearchConfig()
    )
    return ConversationSearch(max_results=config.max_results)
