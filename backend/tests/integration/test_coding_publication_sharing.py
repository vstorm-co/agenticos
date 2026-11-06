"""Edit-sharing and personal coding publication serialize on the same conversation."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.conversation import Conversation
from app.db.models.organization import OrganizationMember
from app.repositories import conversation_share_repo
from app.services.conversation_share import ConversationShareService
from tests.integration.virtual_table_support import make_org, make_user

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_edit_sharing_waits_until_private_publication_commits(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        owner, collaborator = await make_user(setup), await make_user(setup)
        org = await make_org(setup, owner=owner)
        setup.add(
            OrganizationMember(organization_id=org.id, user_id=collaborator.id, role="member")
        )
        chat = Conversation(organization_id=org.id, user_id=owner.id, title="Publication fence")
        setup.add(chat)
        await setup.commit()

    async def share() -> None:
        async with factory() as db:
            await ConversationShareService(db).share_conversation(
                chat.id, owner.id, shared_with=collaborator.id, permission="edit"
            )
            await db.commit()

    async with factory() as publication:
        assert not await conversation_share_repo.lock_private_publication(
            publication, chat.id, uuid4()
        )
        assert await conversation_share_repo.lock_private_publication(publication, chat.id, org.id)
        pending = asyncio.create_task(share())
        try:
            await asyncio.sleep(0.2)
            assert not pending.done()
            # Represents the archive write: no collaborator has edit access yet.
            assert (
                await conversation_share_repo.get_share(publication, chat.id, collaborator.id)
                is None
            )
            await publication.commit()
            await asyncio.wait_for(pending, timeout=3)
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    async with factory() as verify:
        granted = await conversation_share_repo.get_share(verify, chat.id, collaborator.id)
        assert granted is not None and granted.permission == "edit"
