"""Whether a phone number's link to an account is still trusted (#2082)."""

from app.db.session import get_db_context
from app.repositories import channel_identity_repo
from app.services.channels.router import ChannelMessageRouter


async def link_has_lapsed(phone: str) -> bool:
    """Whether this number's link to an account is older than the deployment trusts.

    Asked before a digit is taken as the decision on a pending approval: the router drops
    a lapsed link when the next ordinary message arrives, and a press does not pass through
    it, so without this a prompt sent just before the boundary would stay answerable.
    """
    async with get_db_context() as db:
        identity = await channel_identity_repo.get_by_platform_user(db, "sms", phone)
    return identity is not None and ChannelMessageRouter._sms_link_lapsed("sms", identity)
