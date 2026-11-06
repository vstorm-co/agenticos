"""Drafts capability - text for somebody to send, as a card with a copy button."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.drafts._capability import Drafts
from app.agents.capabilities.drafts._spec import DRAFTS_CAPABILITY_ID, WRITE_DRAFT
from app.agents.capabilities.drafts._toolset import DraftsToolset

__all__ = ["DRAFTS_CAPABILITY_ID", "WRITE_DRAFT", "Drafts", "DraftsToolset"]


@register(
    id=DRAFTS_CAPABILITY_ID,
    name="Drafts",
    category="utility",
    description=(
        "Show text the agent writes for somebody to send - an e-mail, a chat reply, "
        "a post - as a card with a copy button on each part."
    ),
    tools=(
        CapabilityToolInfo(
            id=WRITE_DRAFT,
            description=(
                "Show a draft the person will send or paste somewhere else, "
                "as a card they copy from."
            ),
        ),
    ),
    # A call has nowhere to show the card, and reading a draft aloud is not a draft.
    voice="never",
)
def _build(ctx: CapabilityBuildContext) -> Drafts:
    return Drafts()
