"""The caller an embed's voice socket carries (#54, slice 2).

An anonymous visitor under the publisher's role (`publisher_context`, the rule
every embed run follows), with no member identity of their own: the call row
names the embed and the agent, never a person, the way #1797's embed dictation
attributes its usage. A hosted page's visitor calls into the thread their
continuity key holds; a widget's call starts a new conversation each time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import embed_visitor_repo
from app.services.access import publisher_context
from app.services.voice.starter import VoiceCaller

if TYPE_CHECKING:
    # Annotation only: `agent_embed` imports this package for readiness, so a
    # runtime import here would be a cycle.
    from app.services.agent_embed import Admission


async def embed_caller(
    db: AsyncSession, admission: Admission, *, visitor_key: str | None
) -> VoiceCaller:
    """Who is on a call from an admitted embed.

    `visitor_key` is the continuity key already checked for shape; it is read
    only on a hosted page, where it names the visitor's thread. The row is
    claimed here, as the page's chat socket claims it on connect, so a visitor
    whose first words are spoken comes back to the same thread by text.
    """
    embed = admission.embed
    ctx = await publisher_context(
        db, organization_id=embed.organization_id, publisher_user_id=embed.owner_user_id
    )
    page_key = visitor_key if embed.kind == "page" else None
    conversation_id = None
    if page_key is not None:
        visitor = await embed_visitor_repo.claim(db, embed_id=embed.id, visitor_key=page_key)
        conversation_id = visitor.conversation_id
    return VoiceCaller(
        ctx=ctx,
        user_id=None,
        user_name=None,
        surface="embed",
        anonymous=True,
        auth_token=None,
        embed_id=embed.id,
        agent_id=embed.agent_id,
        conversation_id=conversation_id,
        visitor_key=page_key,
        # A `jwt` visitor's subject names the thread, as a text conversation on
        # the widget does; an anonymous one has nothing to name it by.
        conversation_title=(
            f"{embed.name} - {admission.visitor} - voice call"
            if admission.visitor is not None
            else f"{embed.name} - voice call"
        ),
        embed=embed,
    )
