"""What this deployment holds about one person - handed over, and removed.

Against a real database, because both halves of #1421 are facts about rows and
cascades that a mock cannot answer:

- the export reaches the tables the inventory in `docs/security.md` lists, and
  stops at the ones it says are the organization's;
- the deletion removes what *no cascade reaches* - agent notes keyed by a string
  with no foreign key, and platform identities whose key is `SET NULL` and so
  leaves the row behind holding a Slack id about somebody who is gone.

The second is the one that was actually broken. `UserService.delete` relied on
cascades, and those two tables have none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.memory_keys import person_owner_key
from app.db.models.agent import Agent
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Message
from app.db.models.memory import AgentMemoryFile
from app.db.models.organization import Organization, OrganizationMember
from app.repositories import conversation_repo, personal_data_repo, session_repo, user_repo
from app.services.conversation import ConversationService
from app.services.file_storage import LocalFileStorage, delete_files_best_effort
from app.services.personal_data import PersonalDataService
from app.services.user import UserService

pytestmark = pytest.mark.anyio


async def _person(db, email: str):
    return await user_repo.create(db, email=email, hashed_password="not-a-real-hash")


async def _org_and_agent(db) -> tuple[Organization, Agent]:
    """A real organization and agent, because both tables have a foreign key to one."""
    owner = await _person(db, f"owner-{uuid4().hex[:8]}@example.com")
    organization = Organization(
        id=uuid4(),
        name="Acme",
        slug=f"acme-{uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid4(), organization_id=organization.id, user_id=owner.id, role="owner"
        )
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization.id,
        slug=f"clerk-{uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return organization, agent


async def _note_about(db, user_id: UUID, *, organization_id: UUID, agent_id: UUID) -> None:
    db.add(
        AgentMemoryFile(
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=person_owner_key(user_id),
            name=f"preferences-{uuid4().hex[:8]}.md",
            content="Prefers short answers.",
        )
    )
    await db.flush()


async def _identity_for(db, user_id: UUID | None, *, platform_user_id: str) -> ChannelIdentity:
    identity = ChannelIdentity(
        platform="slack",
        platform_user_id=platform_user_id,
        platform_username="jane",
        user_id=user_id,
    )
    db.add(identity)
    await db.flush()
    return identity


class TestTheExport:
    async def test_it_carries_the_threads_they_started_with_their_turns(self, db):
        user = await _person(db, "export-threads@example.com")
        user_id = user.id
        organization, _ = await _org_and_agent(db)
        conversation = await conversation_repo.create_conversation(
            db,
            organization_id=organization.id,
            user_id=user_id,
            title="About the refund policy",
        )
        await conversation_repo.create_message(
            db, conversation_id=conversation.id, role="user", content="What is the window?"
        )
        await conversation_repo.create_message(
            db, conversation_id=conversation.id, role="assistant", content="Thirty days."
        )

        export = await PersonalDataService(db).export(user_id, actor_user_id=user_id)

        assert [row["title"] for row in export.conversations] == ["About the refund policy"]
        # Answers included: a transcript with every second turn removed answers
        # nothing, and the question asked is what the answer was to.
        assert [row["content"] for row in export.messages] == [
            "What is the window?",
            "Thirty days.",
        ]

    async def test_it_carries_what_agents_wrote_down_about_them(self, db):
        """The least obvious half of "what do you hold about me", and the one a
        person is most surprised by."""
        user = await _person(db, "export-memory@example.com")
        user_id = user.id
        organization, agent = await _org_and_agent(db)
        await _note_about(db, user_id, organization_id=organization.id, agent_id=agent.id)

        export = await PersonalDataService(db).export(user_id, actor_user_id=user_id)

        assert [row["content"] for row in export.memory] == ["Prefers short answers."]

    async def test_it_carries_no_credential_anywhere(self, db):
        """A session row holds a hash of a refresh token, and an export is a file
        a person downloads and a laptop keeps."""
        user = await _person(db, "export-no-credential@example.com")
        user_id = user.id
        await session_repo.create(
            db,
            user_id=user_id,
            refresh_token_hash="a-hash-nobody-should-see",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )

        export = await PersonalDataService(db).export(user_id, actor_user_id=user_id)

        assert len(export.sessions) == 1
        blob = str(export.model_dump())
        assert "a-hash-nobody-should-see" not in blob
        assert "not-a-real-hash" not in blob

    @pytest.mark.security
    async def test_it_carries_nothing_of_anybody_else_s(self, db):
        """The threads of the person asking, never the organization's."""
        mine = await _person(db, "export-mine@example.com")
        theirs = await _person(db, "export-theirs@example.com")
        my_id = mine.id
        organization, _ = await _org_and_agent(db)
        await conversation_repo.create_conversation(
            db, organization_id=organization.id, user_id=theirs.id, title="Not yours"
        )

        export = await PersonalDataService(db).export(my_id, actor_user_id=my_id)

        assert export.conversations == []

    async def test_the_request_is_recorded_even_when_it_is_your_own(self, db):
        """An export is the shape of a breach when the caller is not who they
        claim to be, and the entry is what makes that readable afterwards."""
        user = await _person(db, "export-audited@example.com")
        user_id = user.id

        await PersonalDataService(db).export(user_id, actor_user_id=user_id)

        rows = (
            (
                await db.execute(
                    select(AppAdminAuditLog).where(
                        AppAdminAuditLog.action == "personal_data.exported"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].target_id == str(user_id)
        assert rows[0].details is not None
        assert rows[0].details["own_request"] is True

    async def test_an_administrators_reason_is_recorded_verbatim(self, db):
        user = await _person(db, "export-with-reason@example.com")
        admin = await _person(db, "export-admin@example.com")

        await PersonalDataService(db).export(
            user.id, actor_user_id=admin.id, reason="DPO request ticket 4471"
        )

        row = (
            (
                await db.execute(
                    select(AppAdminAuditLog).where(
                        AppAdminAuditLog.action == "personal_data.exported"
                    )
                )
            )
            .scalars()
            .one()
        )
        assert row.details is not None
        assert row.details["reason"] == "DPO request ticket 4471"
        assert row.details["own_request"] is False


class TestWhatDeletionRemoves:
    async def test_agent_notes_about_them_go_with_the_account(self, db):
        """**The gap this closes.** `owner_key` is a string - `person:<user_id>` -
        with no foreign key, so deleting the row it names left every note behind:
        personal data about somebody who asked to be forgotten, keyed by an id
        that no longer resolves to anybody."""
        user = await _person(db, "purge-memory@example.com")
        user_id = user.id
        organization, agent = await _org_and_agent(db)
        await _note_about(db, user_id, organization_id=organization.id, agent_id=agent.id)

        await UserService(db).delete(user_id)

        remaining = (
            await db.execute(
                select(func.count())
                .select_from(AgentMemoryFile)
                .where(AgentMemoryFile.owner_key == person_owner_key(user_id))
            )
        ).scalar_one()
        assert remaining == 0

    async def test_their_platform_identities_go_rather_than_being_unlinked(self, db):
        """`SET NULL` leaves the row: a Slack user id, a username and a display
        name about somebody whose account is gone, linked to nobody and reachable
        by nothing."""
        user = await _person(db, "purge-identity@example.com")
        user_id = user.id
        await _identity_for(db, user_id, platform_user_id="U-GONE")

        await UserService(db).delete(user_id)

        remaining = (
            await db.execute(
                select(func.count())
                .select_from(ChannelIdentity)
                .where(ChannelIdentity.platform_user_id == "U-GONE")
            )
        ).scalar_one()
        assert remaining == 0

    @pytest.mark.security
    async def test_nobody_else_s_notes_or_identities_are_touched(self, db):
        """The purge is keyed on the person, and a key built from a uuid is not a
        prefix match waiting to happen - but a deletion that reached a
        colleague's notes would be the worst possible failure of this feature."""
        going = await _person(db, "purge-going@example.com")
        staying = await _person(db, "purge-staying@example.com")
        going_id, staying_id = going.id, staying.id
        organization, agent = await _org_and_agent(db)
        await _note_about(db, going_id, organization_id=organization.id, agent_id=agent.id)
        await _note_about(db, staying_id, organization_id=organization.id, agent_id=agent.id)
        await _identity_for(db, staying_id, platform_user_id="U-STAYS")

        await UserService(db).delete(going_id)

        kept = (
            await db.execute(
                select(func.count())
                .select_from(AgentMemoryFile)
                .where(AgentMemoryFile.owner_key == person_owner_key(staying_id))
            )
        ).scalar_one()
        assert kept == 1
        identities = (
            await db.execute(
                select(func.count())
                .select_from(ChannelIdentity)
                .where(ChannelIdentity.platform_user_id == "U-STAYS")
            )
        ).scalar_one()
        assert identities == 1

    async def test_an_identity_that_was_never_linked_is_left_where_it_is(self, db):
        """An unlinked identity is not this person's residue - it is a platform
        account nobody has claimed, and claiming it is somebody's next sign-in."""
        user = await _person(db, "purge-unlinked@example.com")
        user_id = user.id
        await _identity_for(db, None, platform_user_id="U-UNCLAIMED")

        await UserService(db).delete(user_id)

        remaining = (
            await db.execute(
                select(func.count())
                .select_from(ChannelIdentity)
                .where(ChannelIdentity.platform_user_id == "U-UNCLAIMED")
            )
        ).scalar_one()
        assert remaining == 1


class TestDeletingYourOwnChatHistory:
    """FA-015: a person removes their own threads without an administrator.

    The route has existed; what it did to what the thread *carried* had never
    been asserted. The answer is now: the turns go with it (cascade), and the
    attachments' bytes are unlinked - which they were not, because
    `chat_files.message_id` cascades away the row that named the file and leaves
    the file (#1421).
    """

    async def test_the_turns_go_with_the_thread(self, db):
        user = await _person(db, "fa015-turns@example.com")
        organization, _ = await _org_and_agent(db)
        conversation = await conversation_repo.create_conversation(
            db, organization_id=organization.id, user_id=user.id, title="Mine"
        )
        await conversation_repo.create_message(
            db, conversation_id=conversation.id, role="user", content="Delete this."
        )
        conversation_id = conversation.id

        await ConversationService(db).delete_conversation(
            conversation_id, organization_id=organization.id, user_id=user.id
        )

        remaining = (
            await db.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation_id)
            )
        ).scalar_one()
        assert remaining == 0

    async def test_the_attachments_bytes_are_unlinked(self, db, tmp_path, monkeypatch):
        """The row cascades away and the file did not, which is personal data
        kept after somebody asked for it to be deleted and reachable by nothing."""
        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
        user = await _person(db, "fa015-attachment@example.com")
        organization, _ = await _org_and_agent(db)
        conversation = await conversation_repo.create_conversation(
            db, organization_id=organization.id, user_id=user.id, title="With a file"
        )
        message = await conversation_repo.create_message(
            db, conversation_id=conversation.id, role="user", content="Here it is."
        )
        stored = await LocalFileStorage(base_dir=tmp_path).save(
            str(user.id), "receipt.pdf", b"%PDF-1.7"
        )
        db.add(
            ChatFile(
                user_id=user.id,
                message_id=message.id,
                filename="receipt.pdf",
                storage_path=stored,
                mime_type="application/pdf",
                size=8,
                file_type="pdf",
            )
        )
        await db.flush()

        paths = await personal_data_repo.attachment_paths_in(db, conversation.id)
        assert paths == [stored]

        await delete_files_best_effort(paths)

        assert not (tmp_path / stored).exists()

    @pytest.mark.security
    async def test_somebody_else_s_thread_is_not_theirs_to_delete(self, db):
        """Self-service means their own, and the ownership check is in the
        service rather than at the route, so every caller gets it."""
        mine = await _person(db, "fa015-mine@example.com")
        theirs = await _person(db, "fa015-theirs@example.com")
        organization, _ = await _org_and_agent(db)
        conversation = await conversation_repo.create_conversation(
            db, organization_id=organization.id, user_id=theirs.id, title="Not yours"
        )
        conversation_id = conversation.id

        with pytest.raises(NotFoundError):
            await ConversationService(db).delete_conversation(
                conversation_id, organization_id=organization.id, user_id=mine.id
            )
