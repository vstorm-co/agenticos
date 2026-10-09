"""Ask the user - a card of multiple-choice questions, mid-run (#2064)."""

from pydantic_ai_harness.ask_user import TOOL_NAME

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.ask_user._capability import AskTheUser, through_the_surface

__all__ = ["ASK_USER_CAPABILITY_ID", "AskTheUser"]

ASK_USER_CAPABILITY_ID = "ask_user"


@register(
    id=ASK_USER_CAPABILITY_ID,
    name="Ask the user",
    category="utility",
    description=(
        "Let the agent ask the person it is working for a few multiple-choice "
        "questions, shown as a card, instead of guessing."
    ),
    tools=(
        CapabilityToolInfo(
            id=TOOL_NAME,
            description="Ask the user one or more multiple-choice questions and wait for the answers.",
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> AskTheUser:
    return AskTheUser(answerer=through_the_surface)
