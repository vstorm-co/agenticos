"""Calls to the member's opted-in number and allowlisted live-call handoff."""

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.schemas.telephony import PhoneCallsConfig

from ._capability import PhoneCalls

__all__ = ["PhoneCalls"]


@register(
    id="phone_calls",
    name="Telephone calls",
    category="channels",
    description="Call the member's opted-in number, read spoken reports and transfer a live call to authorized contacts.",
    config_schema=PhoneCallsConfig,
    voice="live",
    tools=(
        CapabilityToolInfo(
            id="get_phone_contact_policy",
            description="Read the member's telephone consent, importance criteria and current agent's open cases.",
        ),
        CapabilityToolInfo(
            id="list_phone_transfer_contacts",
            description="List this live call's allowlisted contacts currently accepting transfers, without phone numbers.",
        ),
        CapabilityToolInfo(
            id="call_me",
            description="Queue a call to the member's own verified and opted-in number.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="transfer_phone_call",
            description="Transfer this live telephone call to one explicitly allowlisted contact.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="end_phone_call",
            description="End only the telephone call this live run owns.",
            side_effecting=False,
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> PhoneCalls:
    config = ctx.config
    if not isinstance(config, PhoneCallsConfig):
        raise TypeError("Telephone calls need a validated endpoint binding")
    return PhoneCalls(endpoint_id=config.endpoint_id)
