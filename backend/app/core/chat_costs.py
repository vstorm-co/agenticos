"""Chat spend disclosure; accounting and run authorization remain independent."""

import enum


class ChatCostVisibility(enum.StrEnum):
    EVERYONE = "everyone"
    SPEND_PRIVILEGED = "spend_privileged"
    NOBODY = "nobody"


def chat_cost_policy(value: str | None) -> ChatCostVisibility:
    return ChatCostVisibility.EVERYONE if value is None else ChatCostVisibility(value)


def permits_chat_costs(
    policy: ChatCostVisibility, *, available: bool | None, spend_privileged: bool
) -> bool:
    return available is not False and (
        policy is ChatCostVisibility.EVERYONE
        or (policy is ChatCostVisibility.SPEND_PRIVILEGED and spend_privileged)
    )
