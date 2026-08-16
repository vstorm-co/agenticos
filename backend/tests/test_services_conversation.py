"""Tests for ConversationService (PostgreSQL async variant)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, SystemPromptPart

from app.core.exceptions import BadRequestError, NotFoundError
from app.repositories import conversation_repo
from app.services.conversation import ConversationService

# Every conversation belongs to a tenant; the service refuses reads from another one.
TEST_ORG_ID = uuid4()


class MockConversation:
    """Mock conversation for testing."""

    def __init__(
        self,
        id=None,
        title="Test Conversation",
        user_id=None,
        is_archived=False,
        organization_id=None,
    ):
        self.id = id or uuid4()
        self.title = title
        self.user_id = user_id
        self.organization_id = organization_id or TEST_ORG_ID
        self.is_archived = is_archived
        # A row always has these; a stand-in without them passes tests that the
        # real object would fail the moment anything serializes it.
        self.created_at = datetime(2026, 7, 27, tzinfo=UTC)
        self.updated_at = None
        self.messages: list[Any] = []
        self.summary_messages: list[dict[str, Any]] | None = None
        self.summary_ordinal: int | None = None
        self.overhead_tokens: int | None = None


class MockMessage:
    """Mock message for testing."""

    def __init__(
        self,
        id=None,
        conversation_id=None,
        role="user",
        content="Hello",
        model_name=None,
        tokens_used=None,
        run_id=None,
    ):
        self.id = id or uuid4()
        self.conversation_id = conversation_id or uuid4()
        self.role = role
        self.content = content
        self.model_name = model_name
        self.tokens_used = tokens_used
        # Which run produced the turn, and therefore how it ended - a listing
        # reads a status off it so a stopped turn can say it was stopped.
        self.run_id = run_id
        # Enough of a row for `MessageRead.model_validate`, which the listing runs
        # when it has a reader to attach ratings for.
        self.created_at = datetime(2026, 8, 16, tzinfo=UTC)
        self.updated_at = None


class MockToolCall:
    """Mock tool call for testing."""

    def __init__(
        self,
        id=None,
        message_id=None,
        tool_name="test_tool",
        args=None,
        result=None,
        status="pending",
    ):
        self.id = id or uuid4()
        self.message_id = message_id or uuid4()
        self.tool_name = tool_name
        self.args = args or {}
        self.result = result
        self.status = status


class TestConversationServiceGetConversation:
    """Tests for get_conversation with ownership check."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_get_conversation_returns_conversation(self, service: ConversationService):
        """get_conversation returns conversation when found."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)

            result = await service.get_conversation(conv_id, organization_id=TEST_ORG_ID)

            assert result.id == conv_id
            mock_repo.get_conversation_by_id.assert_called_once_with(
                service.db, conv_id, include_messages=False
            )

    @pytest.mark.anyio
    async def test_a_channel_turn_is_read_back_with_the_name_that_wrote_it(
        self, service: ConversationService
    ):
        """A thread several people spoke in renders as several people, or it reads
        as one person talking to themselves."""
        identity_id = uuid4()
        identity = MagicMock(id=identity_id, platform_username="kacper.wlodarczyk")
        conversation = MockConversation()
        wrote = MagicMock(id=uuid4(), channel_identity_id=identity_id)
        # `author=None` explicitly: a bare mock invents the attribute, and then the
        # assertion below would pass whatever the code did.
        typed = MagicMock(id=uuid4(), channel_identity_id=None, author=None)
        conversation.messages = [wrote, typed]

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_repo.authors_of = AsyncMock(return_value={identity_id: identity})

            await service.get_conversation(
                conversation.id, include_messages=True, organization_id=TEST_ORG_ID
            )

        assert wrote.author is identity
        assert typed.author is None, "nothing typed into the dashboard has a chat account"
        mock_repo.authors_of.assert_awaited_once_with(service.db, [identity_id])

    @pytest.mark.anyio
    async def test_a_dashboard_thread_asks_for_no_authors_at_all(
        self, service: ConversationService
    ):
        """One query per page, and not even that when there is nothing to name."""
        conversation = MockConversation()
        conversation.messages = [MagicMock(id=uuid4(), channel_identity_id=None)]

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_repo.authors_of = AsyncMock(return_value={})

            await service.get_conversation(
                conversation.id, include_messages=True, organization_id=TEST_ORG_ID
            )

        mock_repo.authors_of.assert_awaited_once_with(service.db, [])

    @pytest.mark.anyio
    async def test_get_conversation_not_found_raises(self, service: ConversationService):
        """get_conversation raises NotFoundError when not found."""
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.get_conversation(uuid4(), organization_id=TEST_ORG_ID)

    @pytest.mark.anyio
    async def test_get_conversation_with_messages(self, service: ConversationService):
        """get_conversation passes include_messages to repository."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)

            result = await service.get_conversation(
                conv_id, include_messages=True, organization_id=TEST_ORG_ID
            )

            assert result.id == conv_id
            mock_repo.get_conversation_by_id.assert_called_once_with(
                service.db, conv_id, include_messages=True
            )

    @pytest.mark.anyio
    async def test_get_conversation_wrong_user_raises(self, service: ConversationService):
        """get_conversation raises NotFoundError when user_id doesn't match and no share exists."""
        conv_id = uuid4()
        owner_id = uuid4()
        other_user_id = uuid4()
        mock_conv = MockConversation(id=conv_id, user_id=owner_id)

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_membership.confirms_participation = AsyncMock(return_value=False)

            with pytest.raises(NotFoundError):
                await service.get_conversation(
                    conv_id, user_id=other_user_id, organization_id=TEST_ORG_ID
                )

    @pytest.mark.anyio
    async def test_get_conversation_correct_user_succeeds(self, service: ConversationService):
        """get_conversation succeeds when user_id matches."""
        conv_id = uuid4()
        user_id = uuid4()
        mock_conv = MockConversation(id=conv_id, user_id=user_id)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)

            result = await service.get_conversation(
                conv_id, user_id=user_id, organization_id=TEST_ORG_ID
            )

            assert result.id == conv_id

    @pytest.mark.anyio
    async def test_get_conversation_no_user_id_filter_succeeds(self, service: ConversationService):
        """get_conversation succeeds when no user_id filter is provided."""
        conv_id = uuid4()
        owner_id = uuid4()
        mock_conv = MockConversation(id=conv_id, user_id=owner_id)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)

            result = await service.get_conversation(conv_id, organization_id=TEST_ORG_ID)

            assert result.id == conv_id

    @pytest.mark.anyio
    async def test_get_conversation_null_owner_refuses_a_non_participant(
        self, service: ConversationService
    ):
        """A room thread has no owner, so the owner guard used to be skipped and
        any member of the organization could read one they never spoke in. It is
        readable now only by a participant or a share."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id, user_id=None)

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_membership.confirms_participation = AsyncMock(return_value=False)

            with pytest.raises(NotFoundError):
                await service.get_conversation(
                    conv_id, user_id=uuid4(), organization_id=TEST_ORG_ID
                )

    @pytest.mark.anyio
    async def test_get_conversation_null_owner_allows_a_participant(
        self, service: ConversationService
    ):
        """The other half: a participant the platform still places in the
        channel may open it. Speaking alone stopped being enough with #641."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id, user_id=None)

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_membership.confirms_participation = AsyncMock(return_value=True)

            result = await service.get_conversation(
                conv_id, user_id=uuid4(), organization_id=TEST_ORG_ID
            )

            assert result.id == conv_id


class TestParticipationDoesNotCarryTheWrite:
    """Speaking in a room is a claim on being shown the thread, not on a row
    somebody owns; only an ownerless thread is its participants' to change (#701).

    Every mutating method authorizes by resolving the conversation, so widening the
    read to a room's participants (#639) widened those with it: a Viewer who said
    one thing in a channel could delete the room's transcript, rename it, or append
    a `role: "assistant"` turn that everybody reads in `/chat` and the model is
    handed back as its own words on the next turn. `_may_write` is what keeps the
    two questions apart, so each verb is pinned rather than the helper.
    """

    @pytest.fixture
    def service(self) -> ConversationService:
        return ConversationService(AsyncMock())

    @staticmethod
    def _room(owner_id):
        """A room thread owned by whoever spoke in it first and had linked."""
        return MockConversation(id=uuid4(), user_id=owner_id)

    @pytest.mark.anyio
    async def test_a_participant_may_open_a_thread_they_may_not_change(
        self, service: ConversationService
    ):
        """Both halves in one test on purpose: a refusal that also refused the read
        would pass a write test while breaking the feature #639 exists for."""
        speaker = uuid4()
        conversation = self._room(uuid4())

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_membership.confirms_participation = AsyncMock(return_value=True)

            opened = await service.get_conversation(
                conversation.id, user_id=speaker, organization_id=TEST_ORG_ID
            )
            assert opened.id == conversation.id

            with pytest.raises(NotFoundError):
                await service.update_conversation(
                    conversation.id,
                    MagicMock(),
                    user_id=speaker,
                    organization_id=TEST_ORG_ID,
                )

    @pytest.mark.anyio
    async def test_a_participant_may_not_delete_the_room_transcript(
        self, service: ConversationService
    ):
        speaker = uuid4()
        conversation = self._room(uuid4())

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_repo.delete_conversation = AsyncMock()
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_membership.confirms_participation = AsyncMock(return_value=True)

            with pytest.raises(NotFoundError):
                await service.delete_conversation(
                    conversation.id, user_id=speaker, organization_id=TEST_ORG_ID
                )

            mock_repo.delete_conversation.assert_not_called()

    @pytest.mark.anyio
    async def test_a_participant_may_not_archive_the_room_thread(
        self, service: ConversationService
    ):
        speaker = uuid4()
        conversation = self._room(uuid4())

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_repo.archive_conversation = AsyncMock()
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_membership.confirms_participation = AsyncMock(return_value=True)

            with pytest.raises(NotFoundError):
                await service.archive_conversation(
                    conversation.id, user_id=speaker, organization_id=TEST_ORG_ID
                )

            mock_repo.archive_conversation.assert_not_called()

    @pytest.mark.anyio
    async def test_a_participant_may_not_append_a_turn_as_the_agent(
        self, service: ConversationService
    ):
        """The one with teeth beyond the thread: an appended assistant turn is fed
        back to the model as its own words by the next channel turn's history."""
        speaker = uuid4()
        conversation = self._room(uuid4())

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_repo.create_message = AsyncMock()
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_membership.confirms_participation = AsyncMock(return_value=True)

            with pytest.raises(NotFoundError):
                await service.add_message(
                    conversation.id,
                    MagicMock(),
                    user_id=speaker,
                    organization_id=TEST_ORG_ID,
                )

            mock_repo.create_message.assert_not_called()

    @pytest.mark.anyio
    async def test_a_share_still_carries_the_write(self, service: ConversationService):
        """Sharing is the deliberate act participation is not."""
        reader = uuid4()
        conversation = self._room(uuid4())

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_repo.archive_conversation = AsyncMock(return_value=conversation)
            mock_share_repo.get_share = AsyncMock(return_value=MagicMock())

            archived = await service.archive_conversation(
                conversation.id, user_id=reader, organization_id=TEST_ORG_ID
            )

            assert archived.id == conversation.id

    @pytest.mark.anyio
    async def test_the_owner_still_changes_their_own_thread(self, service: ConversationService):
        owner = uuid4()
        conversation = MockConversation(id=uuid4(), user_id=owner)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_repo.archive_conversation = AsyncMock(return_value=conversation)

            archived = await service.archive_conversation(
                conversation.id, user_id=owner, organization_id=TEST_ORG_ID
            )

            assert archived.id == conversation.id

    @pytest.mark.anyio
    async def test_a_thread_nobody_owns_is_not_a_strangers_to_delete(
        self, service: ConversationService
    ):
        """A room nobody linked an account in has no owner, so the owner guard
        used to be skipped and any member of the organization could delete it
        (#701). The write now stops at the same set the read does."""
        conversation = MockConversation(id=uuid4(), user_id=None)

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_repo.delete_conversation = AsyncMock()
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_membership.confirms_participation = AsyncMock(return_value=False)

            with pytest.raises(NotFoundError):
                await service.delete_conversation(
                    conversation.id, user_id=uuid4(), organization_id=TEST_ORG_ID
                )

            mock_repo.delete_conversation.assert_not_called()

    @pytest.mark.anyio
    async def test_a_thread_nobody_owns_is_its_participants_to_tidy(
        self, service: ConversationService
    ):
        """With no owner to be taken from, speaking in the room is the only claim
        anybody has, so it carries the write - exactly the set the read admits."""
        conversation = MockConversation(id=uuid4(), user_id=None)

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
            mock_repo.delete_conversation = AsyncMock()
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_membership.confirms_participation = AsyncMock(return_value=True)

            assert await service.delete_conversation(
                conversation.id, user_id=uuid4(), organization_id=TEST_ORG_ID
            )


class TestConversationServiceListConversations:
    """Tests for list_conversations."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_list_conversations_returns_tuple(self, service: ConversationService):
        """list_conversations returns (items, total) tuple."""
        mock_convs = [MockConversation(), MockConversation()]

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversations_by_user = AsyncMock(return_value=mock_convs)
            mock_repo.count_conversations = AsyncMock(return_value=2)
            mock_repo.agents_in_conversations = AsyncMock(return_value={})

            items, total = await service.list_conversations(
                skip=0, limit=50, organization_id=TEST_ORG_ID
            )

            assert len(items) == 2
            assert total == 2

    @pytest.mark.anyio
    async def test_list_conversations_with_pagination(self, service: ConversationService):
        """list_conversations passes skip and limit to repository."""
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversations_by_user = AsyncMock(return_value=[])
            mock_repo.count_conversations = AsyncMock(return_value=0)
            mock_repo.agents_in_conversations = AsyncMock(return_value={})

            await service.list_conversations(skip=10, limit=5, organization_id=TEST_ORG_ID)

            call_kwargs = mock_repo.get_conversations_by_user.call_args
            assert call_kwargs[1]["skip"] == 10
            assert call_kwargs[1]["limit"] == 5

    @pytest.mark.anyio
    async def test_list_conversations_include_archived(self, service: ConversationService):
        """list_conversations passes include_archived to repository."""
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversations_by_user = AsyncMock(return_value=[])
            mock_repo.count_conversations = AsyncMock(return_value=0)
            mock_repo.agents_in_conversations = AsyncMock(return_value={})

            await service.list_conversations(
                skip=0, limit=50, include_archived=True, organization_id=TEST_ORG_ID
            )

            call_kwargs = mock_repo.get_conversations_by_user.call_args
            assert call_kwargs[1]["include_archived"] is True

    @pytest.mark.anyio
    async def test_the_count_is_narrowed_the_way_the_page_was(self, service: ConversationService):
        """Both repository calls take the same filters, or the total describes
        a different list from the one the caller was handed."""
        agent_id = uuid4()

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversations_by_user = AsyncMock(return_value=[])
            mock_repo.count_conversations = AsyncMock(return_value=0)
            mock_repo.agents_in_conversations = AsyncMock(return_value={})

            await service.list_conversations(
                organization_id=TEST_ORG_ID,
                search="quarterly",
                agent_id=agent_id,
                archived_only=True,
            )

            narrowing = ("search", "agent_id", "include_archived", "archived_only")
            page = mock_repo.get_conversations_by_user.call_args[1]
            count = mock_repo.count_conversations.call_args[1]
            assert {key: page[key] for key in narrowing} == {key: count[key] for key in narrowing}
            assert page["search"] == "quarterly"
            assert page["agent_id"] == agent_id
            assert page["archived_only"] is True

    @pytest.mark.anyio
    async def test_the_sort_reaches_the_repository(self, service: ConversationService):
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversations_by_user = AsyncMock(return_value=[])
            mock_repo.count_conversations = AsyncMock(return_value=0)
            mock_repo.agents_in_conversations = AsyncMock(return_value={})

            await service.list_conversations(
                organization_id=TEST_ORG_ID, sort_by="title", sort_dir="asc"
            )

            call_kwargs = mock_repo.get_conversations_by_user.call_args[1]
            assert (call_kwargs["sort_by"], call_kwargs["sort_dir"]) == ("title", "asc")

    @pytest.mark.anyio
    async def test_a_users_page_carries_the_vetted_participation_set(
        self, service: ConversationService
    ):
        """The membership-confirmed threads reach the page *and* the count - a
        total counted without them contradicts the rows under it - and the repo
        never sees an unvetted claim (#641)."""
        reader = uuid4()
        vetted = {uuid4()}

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversations_by_user = AsyncMock(return_value=[])
            mock_repo.count_conversations = AsyncMock(return_value=0)
            mock_repo.agents_in_conversations = AsyncMock(return_value={})
            mock_membership.confirmed_participant_threads = AsyncMock(return_value=vetted)

            await service.list_conversations(user_id=reader, organization_id=TEST_ORG_ID)

            page = mock_repo.get_conversations_by_user.call_args[1]
            count = mock_repo.count_conversations.call_args[1]
            assert page["participant_conversation_ids"] == vetted
            assert count["participant_conversation_ids"] == vetted
            mock_membership.confirmed_participant_threads.assert_awaited_once_with(
                service.db, user_id=reader, organization_id=TEST_ORG_ID
            )

    @pytest.mark.anyio
    async def test_an_unnarrowed_listing_never_asks_the_platform(
        self, service: ConversationService
    ):
        """No reader means no participation to vet - an admin-shaped listing must
        not spend a membership call per channel."""
        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.channel_membership") as mock_membership,
        ):
            mock_repo.get_conversations_by_user = AsyncMock(return_value=[])
            mock_repo.count_conversations = AsyncMock(return_value=0)
            mock_repo.agents_in_conversations = AsyncMock(return_value={})
            mock_membership.confirmed_participant_threads = AsyncMock()

            await service.list_conversations(organization_id=TEST_ORG_ID)

            mock_membership.confirmed_participant_threads.assert_not_awaited()


class TestConversationServiceCreate:
    """Tests for create_conversation."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_create_conversation(self, service: ConversationService):
        """create_conversation creates and returns a conversation."""
        mock_data = MagicMock()
        mock_data.user_id = uuid4()
        mock_data.title = "Test Conversation"
        mock_conv = MockConversation(title="Test Conversation")

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.create_conversation = AsyncMock(return_value=mock_conv)

            result = await service.create_conversation(mock_data)

            assert result.title == "Test Conversation"
            mock_repo.create_conversation.assert_called_once()


class TestConversationServiceUpdate:
    """Tests for update_conversation with ownership."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_update_conversation_succeeds(self, service: ConversationService):
        """update_conversation updates and returns the conversation."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id)
        updated_conv = MockConversation(id=conv_id, title="Updated Title")
        mock_update = MagicMock()
        mock_update.model_dump.return_value = {"title": "Updated Title"}

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_repo.update_conversation = AsyncMock(return_value=updated_conv)

            result = await service.update_conversation(
                conv_id, mock_update, organization_id=TEST_ORG_ID
            )

            assert result.title == "Updated Title"
            mock_repo.update_conversation.assert_called_once()

    @pytest.mark.anyio
    async def test_update_nonexistent_conversation_raises(self, service: ConversationService):
        """update_conversation raises NotFoundError when conversation not found."""
        mock_update = MagicMock()
        mock_update.model_dump.return_value = {"title": "New Title"}

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.update_conversation(uuid4(), mock_update, organization_id=TEST_ORG_ID)

    @pytest.mark.anyio
    async def test_update_checks_ownership(self, service: ConversationService):
        """update_conversation verifies user owns the conversation."""
        conv_id = uuid4()
        owner_id = uuid4()
        other_id = uuid4()
        mock_conv = MockConversation(id=conv_id, user_id=owner_id)
        mock_update = MagicMock()
        mock_update.model_dump.return_value = {"title": "New Title"}

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_share_repo.get_share = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.update_conversation(
                    conv_id, mock_update, user_id=other_id, organization_id=TEST_ORG_ID
                )


class TestConversationServiceArchive:
    """Tests for archive_conversation with ownership."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_archive_conversation_succeeds(self, service: ConversationService):
        """archive_conversation archives and returns the conversation."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id)
        archived_conv = MockConversation(id=conv_id, is_archived=True)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_repo.archive_conversation = AsyncMock(return_value=archived_conv)

            result = await service.archive_conversation(conv_id, organization_id=TEST_ORG_ID)

            assert result.is_archived is True
            mock_repo.archive_conversation.assert_called_once_with(
                service.db, db_conversation=mock_conv
            )

    @pytest.mark.anyio
    async def test_archive_nonexistent_conversation_raises(self, service: ConversationService):
        """archive_conversation raises NotFoundError when conversation not found."""
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.archive_conversation(uuid4(), organization_id=TEST_ORG_ID)

    @pytest.mark.anyio
    async def test_archive_checks_ownership(self, service: ConversationService):
        """archive_conversation verifies user owns the conversation."""
        conv_id = uuid4()
        owner_id = uuid4()
        other_id = uuid4()
        mock_conv = MockConversation(id=conv_id, user_id=owner_id)

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_share_repo.get_share = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.archive_conversation(
                    conv_id, user_id=other_id, organization_id=TEST_ORG_ID
                )


class TestConversationServiceDelete:
    """Tests for delete_conversation with ownership."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_delete_own_conversation_succeeds(self, service: ConversationService):
        """delete_conversation succeeds for conversation owner."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_repo.delete_conversation = AsyncMock(return_value=None)

            result = await service.delete_conversation(conv_id, organization_id=TEST_ORG_ID)

            assert result is True
            mock_repo.delete_conversation.assert_called_once_with(
                service.db, db_conversation=mock_conv
            )

    @pytest.mark.anyio
    async def test_delete_nonexistent_conversation_raises(self, service: ConversationService):
        """delete_conversation raises NotFoundError when conversation not found."""
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.delete_conversation(uuid4(), organization_id=TEST_ORG_ID)

    @pytest.mark.anyio
    async def test_delete_checks_ownership(self, service: ConversationService):
        """delete_conversation verifies user owns the conversation."""
        conv_id = uuid4()
        owner_id = uuid4()
        other_id = uuid4()
        mock_conv = MockConversation(id=conv_id, user_id=owner_id)

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_share_repo.get_share = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.delete_conversation(
                    conv_id, user_id=other_id, organization_id=TEST_ORG_ID
                )


class TestConversationServiceGetMessage:
    """Tests for get_message."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_get_message_returns_message(self, service: ConversationService):
        """get_message returns message when found."""
        msg_id = uuid4()
        mock_msg = MockMessage(id=msg_id)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_message_by_id = AsyncMock(return_value=mock_msg)

            result = await service.get_message(msg_id)

            assert result.id == msg_id
            mock_repo.get_message_by_id.assert_called_once_with(service.db, msg_id)

    @pytest.mark.anyio
    async def test_get_message_not_found_raises(self, service: ConversationService):
        """get_message raises NotFoundError when not found."""
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_message_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.get_message(uuid4())


class TestConversationServiceListMessages:
    """Tests for list_messages."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_list_messages_returns_tuple(self, service: ConversationService):
        """list_messages returns (items, total) tuple."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id)
        mock_messages = [MockMessage(), MockMessage()]

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_repo.get_messages_by_conversation = AsyncMock(return_value=mock_messages)
            mock_repo.run_statuses = AsyncMock(return_value={})
            mock_repo.count_messages = AsyncMock(return_value=2)
            mock_repo.run_statuses = AsyncMock(return_value={})

            items, total = await service.list_messages(conv_id, organization_id=TEST_ORG_ID)

            assert len(items) == 2
            assert total == 2

    @pytest.mark.anyio
    async def test_list_messages_verifies_conversation_exists(self, service: ConversationService):
        """list_messages raises NotFoundError when conversation not found."""
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.list_messages(uuid4(), organization_id=TEST_ORG_ID)

    @pytest.mark.anyio
    async def test_list_messages_with_pagination(self, service: ConversationService):
        """list_messages passes skip and limit to repository."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_repo.get_messages_by_conversation = AsyncMock(return_value=[])
            mock_repo.run_statuses = AsyncMock(return_value={})
            mock_repo.count_messages = AsyncMock(return_value=0)

            await service.list_messages(conv_id, skip=5, limit=10, organization_id=TEST_ORG_ID)

            call_kwargs = mock_repo.get_messages_by_conversation.call_args
            assert call_kwargs[1]["skip"] == 5
            assert call_kwargs[1]["limit"] == 10

    @pytest.mark.anyio
    async def test_list_messages_with_tool_calls(self, service: ConversationService):
        """list_messages passes include_tool_calls to repository."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_repo.get_messages_by_conversation = AsyncMock(return_value=[])
            mock_repo.run_statuses = AsyncMock(return_value={})
            mock_repo.count_messages = AsyncMock(return_value=0)

            await service.list_messages(
                conv_id, include_tool_calls=True, organization_id=TEST_ORG_ID
            )

            call_kwargs = mock_repo.get_messages_by_conversation.call_args
            assert call_kwargs[1]["include_tool_calls"] is True


class TestConversationServiceAddMessage:
    """Tests for add_message."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_add_message_succeeds(self, service: ConversationService):
        """add_message creates and returns a message."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id)
        mock_msg = MockMessage(conversation_id=conv_id, role="user", content="Hello")
        mock_data = MagicMock()
        mock_data.role = "user"
        mock_data.content = "Hello"
        mock_data.model_name = None
        mock_data.tokens_used = None

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_repo.create_message = AsyncMock(return_value=mock_msg)

            result = await service.add_message(conv_id, mock_data, organization_id=TEST_ORG_ID)

            assert result.content == "Hello"
            assert result.role == "user"
            mock_repo.create_message.assert_called_once()

    @pytest.mark.anyio
    async def test_every_field_the_schema_carries_reaches_the_row(
        self, service: ConversationService
    ):
        """The two at the end were being dropped. `persist_assistant_turn` built an
        `agent_id` and an `agent_version_id`, the model documents why they are
        per-message, and this call did not forward them - so every assistant row in
        the database had a null agent and a null version, and a reloaded transcript
        could not say who said what or under which instructions. Asserted field by
        field rather than "called once", which is what let it pass."""
        from decimal import Decimal

        from app.schemas.conversation import MessageCreate

        conv_id, agent_id, version_id = uuid4(), uuid4(), uuid4()
        data = MessageCreate(
            role="assistant",
            content="answered",
            model_name="gpt-4.1",
            agent_id=agent_id,
            agent_version_id=version_id,
            input_tokens=1200,
            output_tokens=300,
            cost_usd=Decimal("0.0125"),
        )

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=MockConversation(id=conv_id))
            mock_repo.create_message = AsyncMock(return_value=MockMessage())

            await service.add_message(conv_id, data, organization_id=TEST_ORG_ID)

        written = mock_repo.create_message.await_args.kwargs
        assert written["agent_id"] == agent_id
        assert written["agent_version_id"] == version_id
        assert written["input_tokens"] == 1200
        assert written["output_tokens"] == 300
        assert written["cost_usd"] == Decimal("0.0125")

    @pytest.mark.anyio
    async def test_a_run_id_in_the_request_body_reaches_no_row(self, service: ConversationService):
        """`POST /conversations/{id}/messages` binds `MessageCreate` from JSON, so a
        `run_id` the schema accepted would let anybody append their words to another
        organization's run transcript - the route scopes the conversation, and a bare
        run id carries nothing to scope. Which run produced a turn is the runner's to
        say, so it is a keyword on this method and the field is dropped."""
        from app.schemas.conversation import MessageCreate

        conv_id, someone_elses_run = uuid4(), uuid4()
        data = MessageCreate.model_validate(
            {"role": "user", "content": "attached to your run", "run_id": str(someone_elses_run)}
        )

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=MockConversation(id=conv_id))
            mock_repo.create_message = AsyncMock(return_value=MockMessage())

            await service.add_message(conv_id, data, organization_id=TEST_ORG_ID)

        assert mock_repo.create_message.await_args.kwargs["run_id"] is None

    @pytest.mark.anyio
    async def test_the_runner_is_what_puts_a_turn_in_a_runs_transcript(
        self, service: ConversationService
    ):
        from app.schemas.conversation import MessageCreate

        conv_id, run_id = uuid4(), uuid4()
        data = MessageCreate(role="assistant", content="answered")

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=MockConversation(id=conv_id))
            mock_repo.create_message = AsyncMock(return_value=MockMessage())

            await service.add_message(conv_id, data, organization_id=TEST_ORG_ID, run_id=run_id)

        assert mock_repo.create_message.await_args.kwargs["run_id"] == run_id

    @pytest.mark.anyio
    async def test_add_message_to_archived_conversation_raises_bad_request(
        self, service: ConversationService
    ):
        """Archiving closes a thread; a message appended afterwards would silently reopen it."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id, is_archived=True)
        mock_data = MagicMock()

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_repo.create_message = AsyncMock()

            with pytest.raises(BadRequestError):
                await service.add_message(conv_id, mock_data, organization_id=TEST_ORG_ID)

            mock_repo.create_message.assert_not_called()

    @pytest.mark.anyio
    async def test_add_message_verifies_conversation_exists(self, service: ConversationService):
        """add_message raises NotFoundError when conversation not found."""
        mock_data = MagicMock()

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.add_message(uuid4(), mock_data, organization_id=TEST_ORG_ID)


class TestConversationServiceDeleteMessage:
    """Tests for delete_message."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_delete_message_succeeds(self, service: ConversationService):
        """delete_message returns True when message is deleted."""
        msg_id = uuid4()

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.delete_message = AsyncMock(return_value=True)

            result = await service.delete_message(msg_id)

            assert result is True
            mock_repo.delete_message.assert_called_once_with(service.db, msg_id)

    @pytest.mark.anyio
    async def test_delete_message_not_found_raises(self, service: ConversationService):
        """delete_message raises NotFoundError when message not found."""
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.delete_message = AsyncMock(return_value=False)

            with pytest.raises(NotFoundError):
                await service.delete_message(uuid4())


class TestConversationServiceToolCalls:
    """Tests for tool call methods."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_get_tool_call_returns_tool_call(self, service: ConversationService):
        """get_tool_call returns tool call when found."""
        tc_id = uuid4()
        mock_tc = MockToolCall(id=tc_id)

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_tool_call_by_id = AsyncMock(return_value=mock_tc)

            result = await service.get_tool_call(tc_id)

            assert result.id == tc_id

    @pytest.mark.anyio
    async def test_get_tool_call_not_found_raises(self, service: ConversationService):
        """get_tool_call raises NotFoundError when not found."""
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_tool_call_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.get_tool_call(uuid4())

    @pytest.mark.anyio
    async def test_start_tool_call_succeeds(self, service: ConversationService):
        """start_tool_call records and returns a new tool call."""
        msg_id = uuid4()
        mock_msg = MockMessage(id=msg_id)
        mock_tc = MockToolCall(message_id=msg_id, tool_name="search")
        mock_data = MagicMock()
        mock_data.tool_call_id = str(uuid4())
        mock_data.tool_name = "search"
        mock_data.args = {"query": "test"}
        mock_data.started_at = None

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_message_by_id = AsyncMock(return_value=mock_msg)
            mock_repo.create_tool_call = AsyncMock(return_value=mock_tc)

            result = await service.start_tool_call(msg_id, mock_data)

            assert result.tool_name == "search"
            mock_repo.create_tool_call.assert_called_once()
            assert mock_repo.create_tool_call.call_args.kwargs["status"] == "running"

    @pytest.mark.anyio
    async def test_a_parked_tool_call_is_stored_awaiting_approval(
        self, service: ConversationService
    ):
        """The status is what a reloaded conversation reads: written `running`,
        the one call somebody has to decide about replayed as a step that ran and
        the page said nothing about waiting (#601)."""
        msg_id = uuid4()
        mock_data = MagicMock()
        mock_data.tool_call_id = str(uuid4())
        mock_data.tool_name = "send_email"
        mock_data.args = {"to": "ada@example.com"}
        mock_data.started_at = None

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_message_by_id = AsyncMock(return_value=MockMessage(id=msg_id))
            mock_repo.create_tool_call = AsyncMock(
                return_value=MockToolCall(message_id=msg_id, tool_name="send_email")
            )

            await service.start_tool_call(msg_id, mock_data, parked=True)

            assert mock_repo.create_tool_call.call_args.kwargs["status"] == "awaiting_approval"

    @pytest.mark.anyio
    async def test_start_tool_call_verifies_message_exists(self, service: ConversationService):
        """start_tool_call raises NotFoundError when message not found."""
        mock_data = MagicMock()

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_message_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.start_tool_call(uuid4(), mock_data)

    @pytest.mark.anyio
    async def test_complete_tool_call_succeeds(self, service: ConversationService):
        """complete_tool_call marks tool call as completed."""
        tc_id = uuid4()
        mock_tc = MockToolCall(id=tc_id, status="pending")
        completed_tc = MockToolCall(id=tc_id, status="completed", result="success")
        mock_data = MagicMock()
        mock_data.result = "success"
        mock_data.completed_at = None
        mock_data.success = True

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_tool_call_by_id = AsyncMock(return_value=mock_tc)
            mock_repo.complete_tool_call = AsyncMock(return_value=completed_tc)

            result = await service.complete_tool_call(tc_id, mock_data)

            assert result.status == "completed"
            assert result.result == "success"
            mock_repo.complete_tool_call.assert_called_once()

    @pytest.mark.anyio
    async def test_complete_tool_call_not_found_raises(self, service: ConversationService):
        """complete_tool_call raises NotFoundError when tool call not found."""
        mock_data = MagicMock()

        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_tool_call_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.complete_tool_call(uuid4(), mock_data)


class TestConversationServiceLinkFiles:
    """A message may take only the caller's own unlinked files (#706).

    The ids arrive off a socket payload, so before this rule a turn naming
    another user's file id rendered their filename in its own conversation and
    silently pulled the file off the message it already hung on.
    """

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_link_files_empty_list_links_nothing(self, service: ConversationService):
        """link_files_to_message issues no UPDATE for an empty file list."""
        with patch("app.services.conversation.chat_file_repo") as repo:
            repo.get_many = AsyncMock(return_value=[])
            repo.link_to_message = AsyncMock()

            await service.link_files_to_message(uuid4(), [], user_id=uuid4())

        repo.link_to_message.assert_not_awaited()

    @pytest.mark.anyio
    async def test_the_callers_own_unlinked_files_are_linked_as_the_caller(
        self, service: ConversationService
    ):
        """The owner rides into the repository, where the UPDATE's WHERE carries it."""
        msg_id = uuid4()
        user_id = uuid4()
        ids = [uuid4(), uuid4()]

        with patch("app.services.conversation.chat_file_repo") as repo:
            repo.get_many = AsyncMock(
                return_value=[MagicMock(id=fid, message_id=None) for fid in ids]
            )
            repo.link_to_message = AsyncMock(return_value=len(ids))

            await service.link_files_to_message(msg_id, [str(fid) for fid in ids], user_id=user_id)

        linked = repo.link_to_message.await_args.kwargs
        assert (linked["message_id"], linked["file_ids"], linked["user_id"]) == (
            msg_id,
            ids,
            user_id,
        )

    @pytest.mark.anyio
    async def test_an_id_that_is_not_a_uuid_is_refused_before_any_read(
        self, service: ConversationService
    ):
        """A `ValueError` here used to fall into the caller's infrastructure net
        and resurface a step later as a generic failed turn, after the message
        had already been persisted. The refusal names only the malformed ids."""
        good = uuid4()

        with patch("app.services.conversation.chat_file_repo") as repo:
            repo.get_many = AsyncMock()
            repo.link_to_message = AsyncMock()

            with pytest.raises(BadRequestError) as refusal:
                await service.link_files_to_message(
                    uuid4(), [str(good), "not-a-uuid", None], user_id=uuid4()
                )

        assert refusal.value.details == {"file_ids": ["not-a-uuid", "None"]}
        repo.get_many.assert_not_awaited()
        repo.link_to_message.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_row_taken_between_the_read_and_the_update_is_refused(
        self, service: ConversationService
    ):
        """The pre-read and the UPDATE are two statements, so a concurrent turn
        can take the row between them; the repository's count is what keeps the
        race from answering as a message that quietly lost its attachment."""
        contested = uuid4()

        with patch("app.services.conversation.chat_file_repo") as repo:
            repo.get_many = AsyncMock(return_value=[MagicMock(id=contested, message_id=None)])
            repo.link_to_message = AsyncMock(return_value=0)

            with pytest.raises(BadRequestError) as refusal:
                await service.link_files_to_message(uuid4(), [str(contested)], user_id=uuid4())

        assert refusal.value.details == {"file_ids": [contested]}

    @pytest.mark.anyio
    async def test_a_file_that_is_not_the_callers_is_refused_as_missing(
        self, service: ConversationService
    ):
        """Missing, not forbidden: "not yours" would confirm the id exists. And
        refused before the UPDATE, so nothing is silently narrowed."""
        theirs = uuid4()

        with patch("app.services.conversation.chat_file_repo") as repo:
            repo.get_many = AsyncMock(return_value=[])
            repo.link_to_message = AsyncMock()

            with pytest.raises(NotFoundError) as refusal:
                await service.link_files_to_message(uuid4(), [str(theirs)], user_id=uuid4())

        assert refusal.value.details == {"file_ids": [theirs]}
        repo.link_to_message.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_file_already_on_a_message_is_refused_not_moved(
        self, service: ConversationService
    ):
        """Re-linking is refused outright: the silent move is how a victim's own
        transcript lost its attachment, and no legitimate caller re-links."""
        spent = uuid4()

        with patch("app.services.conversation.chat_file_repo") as repo:
            repo.get_many = AsyncMock(return_value=[MagicMock(id=spent, message_id=uuid4())])
            repo.link_to_message = AsyncMock()

            with pytest.raises(BadRequestError) as refusal:
                await service.link_files_to_message(uuid4(), [str(spent)], user_id=uuid4())

        assert refusal.value.details == {"file_ids": [spent]}
        repo.link_to_message.assert_not_awaited()


class TestSayingATurnWasStopped:
    """`run_status` on a listed message.

    A cancelled run leaves a half-written answer that reads exactly like a
    complete one, so the reader believes the agent said all it had to say. The
    status is on the run and the message links to it; carrying it here is what
    lets a transcript mark the turn without a second request per row.
    """

    @pytest.fixture
    def service(self) -> ConversationService:
        return ConversationService(AsyncMock())

    @staticmethod
    async def _listed(service: ConversationService, conv_id):
        """Listed as the transcript route lists them - with a reader, so the
        schema-enriching branch runs rather than the raw-row one."""
        with patch("app.services.conversation.message_rating_repo") as ratings:
            ratings.get_user_ratings_for_messages = AsyncMock(return_value={})
            ratings.get_rating_counts_for_messages = AsyncMock(return_value={})
            return await service.list_messages(
                conv_id, organization_id=TEST_ORG_ID, user_id=uuid4()
            )

    @pytest.mark.anyio
    async def test_a_turn_carries_how_its_run_ended(self, service: ConversationService):
        conv_id = uuid4()
        run_id = uuid4()
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(
                return_value=MockConversation(id=conv_id, organization_id=TEST_ORG_ID)
            )
            mock_repo.get_messages_by_conversation = AsyncMock(
                return_value=[MockMessage(run_id=run_id)]
            )
            mock_repo.count_messages = AsyncMock(return_value=1)
            mock_repo.run_statuses = AsyncMock(return_value={run_id: "cancelled"})

            items, _total = await self._listed(service, conv_id)

        assert items[0].run_status == "cancelled"

    @pytest.mark.anyio
    async def test_a_turn_written_outside_a_run_says_nothing(self, service: ConversationService):
        """A system message, or a prompt whose run row could not be opened."""
        conv_id = uuid4()
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(
                return_value=MockConversation(id=conv_id, organization_id=TEST_ORG_ID)
            )
            mock_repo.get_messages_by_conversation = AsyncMock(return_value=[MockMessage()])
            mock_repo.count_messages = AsyncMock(return_value=1)
            mock_repo.run_statuses = AsyncMock(return_value={})

            items, _total = await self._listed(service, conv_id)

        assert items[0].run_status is None


class TestWhatTheThreadCost:
    """`conversation_cost` - the total beside the page of messages.

    Scoped exactly as `list_messages` is, and for the same reason: a total is
    enough to tell how heavily somebody else's conversation was used.
    """

    @pytest.fixture
    def service(self) -> ConversationService:
        return ConversationService(AsyncMock())

    @pytest.mark.anyio
    async def test_another_tenants_thread_is_not_totalled(self, service: ConversationService):
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.conversation_cost(uuid4(), organization_id=TEST_ORG_ID)

    @pytest.mark.anyio
    async def test_a_thread_nobody_measured_answers_nothing(self, service: ConversationService):
        """Zeroes would be a claim, and this has none to make."""
        conv_id = uuid4()
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(
                return_value=MockConversation(id=conv_id, organization_id=TEST_ORG_ID)
            )
            mock_repo.conversation_cost = AsyncMock(return_value=None)

            assert await service.conversation_cost(conv_id, organization_id=TEST_ORG_ID) is None

    @pytest.mark.anyio
    async def test_the_totals_reach_the_schema_the_client_reads(self, service: ConversationService):
        conv_id = uuid4()
        with patch("app.services.conversation.conversation_repo") as mock_repo:
            mock_repo.get_conversation_by_id = AsyncMock(
                return_value=MockConversation(id=conv_id, organization_id=TEST_ORG_ID)
            )
            mock_repo.conversation_cost = AsyncMock(
                return_value=(3_000, 300, Decimal("0.030000"), True)
            )

            cost = await service.conversation_cost(conv_id, organization_id=TEST_ORG_ID)

        assert cost is not None
        assert (cost.input_tokens, cost.output_tokens) == (3_000, 300)
        assert cost.cost_usd == Decimal("0.030000")
        assert cost.cost_is_partial is True


@pytest.mark.anyio
class TestTheThreadAModelIsGivenBack:
    """A summary is bought once, not once per turn.

    Compaction rewrites the messages of one run, and the thread between turns is
    rebuilt from the transcript - so the summary used to be thrown away at the
    turn boundary and the next turn bought another over a history one turn
    longer. Two consecutive turns of a real conversation each paid for one, the
    second announcing itself as summarising nine messages (#49).
    """

    @staticmethod
    def _row(role: str, content: str, *, used: int | None = None, row_id: Any = None) -> Any:
        message = MockMessage(role=role, content=content, id=row_id)
        message.context_used_tokens = used
        return message

    async def test_a_conversation_with_no_summary_is_read_from_its_transcript(self, monkeypatch):
        conversation = MockConversation()
        monkeypatch.setattr(
            conversation_repo, "get_conversation_by_id", AsyncMock(return_value=conversation)
        )
        recent = AsyncMock(return_value=[self._row("user", "hi"), self._row("assistant", "hello")])
        monkeypatch.setattr(conversation_repo, "get_recent_messages", recent)

        history = await ConversationService(AsyncMock()).model_history(conversation.id, limit=50)

        assert [part.content for message in history for part in message.parts] == ["hi", "hello"]

    async def test_a_summary_replaces_the_turns_it_accounts_for(self, monkeypatch):
        """The whole point: the summarised turns are not read back at all, so the
        next turn has nothing left to summarise a second time."""
        conversation = MockConversation()
        conversation.summary_messages = ModelMessagesTypeAdapter.dump_python(
            [ModelRequest(parts=[SystemPromptPart(content="Summary: they said hello.")])],
            mode="json",
        )
        conversation.summary_ordinal = 4
        monkeypatch.setattr(
            conversation_repo, "get_conversation_by_id", AsyncMock(return_value=conversation)
        )
        after = AsyncMock(return_value=[self._row("user", "and now?")])
        monkeypatch.setattr(conversation_repo, "get_messages_after", after)
        monkeypatch.setattr(conversation_repo, "get_recent_messages", AsyncMock())

        history = await ConversationService(AsyncMock()).model_history(conversation.id, limit=50)

        assert [part.content for message in history for part in message.parts] == [
            "Summary: they said hello.",
            "and now?",
        ]
        assert after.await_args.kwargs["ordinal"] == 4
        conversation_repo.get_recent_messages.assert_not_awaited()

    async def test_the_turn_being_answered_is_not_read_back_as_history(self, monkeypatch):
        """The prompt is written before the run so a refusal cannot lose it, so it
        is a row by the time this reads. Left in, the model is asked twice."""
        conversation = MockConversation()
        prompt_id = uuid4()
        monkeypatch.setattr(
            conversation_repo, "get_conversation_by_id", AsyncMock(return_value=conversation)
        )
        monkeypatch.setattr(
            conversation_repo,
            "get_recent_messages",
            AsyncMock(return_value=[self._row("user", "asked now", row_id=prompt_id)]),
        )

        history = await ConversationService(AsyncMock()).model_history(
            conversation.id, limit=50, exclude_message_id=prompt_id
        )

        assert history == []

    async def test_a_summary_is_recorded_against_everything_written_so_far(self, monkeypatch):
        """Including the turn that produced it. Stored short of the answer, the
        next turn would replay the summary and the answer already inside it."""
        conversation = MockConversation()
        monkeypatch.setattr(
            conversation_repo, "get_conversation_by_id", AsyncMock(return_value=conversation)
        )
        monkeypatch.setattr(conversation_repo, "last_ordinal", AsyncMock(return_value=9))
        stored = AsyncMock()
        monkeypatch.setattr(conversation_repo, "set_summary", stored)

        await ConversationService(AsyncMock()).keep_summary(conversation.id, [{"kind": "request"}])

        assert stored.await_args.kwargs["ordinal"] == 9
        assert stored.await_args.kwargs["messages"] == [{"kind": "request"}]

    async def test_a_summary_for_a_conversation_that_is_gone_is_dropped(self, monkeypatch):
        """A thread deleted while its last turn was still running. The answer has
        already been produced; failing here would lose it to bookkeeping."""
        monkeypatch.setattr(
            conversation_repo, "get_conversation_by_id", AsyncMock(return_value=None)
        )
        stored = AsyncMock()
        monkeypatch.setattr(conversation_repo, "set_summary", stored)

        await ConversationService(AsyncMock()).keep_summary(uuid4(), [{"kind": "request"}])

        stored.assert_not_awaited()

    async def test_a_conversation_that_is_gone_has_no_history(self, monkeypatch):
        monkeypatch.setattr(
            conversation_repo, "get_conversation_by_id", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(conversation_repo, "get_recent_messages", AsyncMock(return_value=[]))

        assert await ConversationService(AsyncMock()).model_history(uuid4(), limit=50) == []


@pytest.mark.anyio
class TestWhatARequestCarriesBeforeAnyMessage:
    """The instructions and every tool schema, which no summary compacts away.

    Measured from a response, so within one run it is unknown until one arrives -
    and a one-request chat turn, which is most of them, never gets that far. Left
    per-run it was `None` for the whole turn, so compaction could not tell a
    window with no room for a summary from one that works, and bought one every
    turn in silence (#49).
    """

    async def test_it_is_recorded_so_the_next_turn_starts_knowing_it(self, monkeypatch):
        conversation = MockConversation()
        monkeypatch.setattr(
            conversation_repo, "get_conversation_by_id", AsyncMock(return_value=conversation)
        )
        stored = AsyncMock()
        monkeypatch.setattr(conversation_repo, "set_overhead", stored)

        await ConversationService(AsyncMock()).keep_overhead(conversation.id, 3_865)

        assert stored.await_args.kwargs["tokens"] == 3_865

    async def test_a_reading_that_has_not_moved_is_not_written_again(self, monkeypatch):
        """It moves only when the agent does - a tool bound, a prompt rewritten -
        so an UPDATE per turn writes the number that was already there."""
        conversation = MockConversation()
        conversation.overhead_tokens = 3_865
        monkeypatch.setattr(
            conversation_repo, "get_conversation_by_id", AsyncMock(return_value=conversation)
        )
        stored = AsyncMock()
        monkeypatch.setattr(conversation_repo, "set_overhead", stored)

        await ConversationService(AsyncMock()).keep_overhead(conversation.id, 3_865)

        stored.assert_not_awaited()

    async def test_a_conversation_that_is_gone_records_nothing(self, monkeypatch):
        monkeypatch.setattr(
            conversation_repo, "get_conversation_by_id", AsyncMock(return_value=None)
        )
        stored = AsyncMock()
        monkeypatch.setattr(conversation_repo, "set_overhead", stored)

        await ConversationService(AsyncMock()).keep_overhead(uuid4(), 3_865)

        stored.assert_not_awaited()
