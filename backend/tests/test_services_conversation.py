"""Tests for ConversationService (PostgreSQL async variant)."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
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
    ):
        self.id = id or uuid4()
        self.conversation_id = conversation_id or uuid4()
        self.role = role
        self.content = content
        self.model_name = model_name
        self.tokens_used = tokens_used


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
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_repo.spoke_in = AsyncMock(return_value=False)

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
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_repo.spoke_in = AsyncMock(return_value=False)

            with pytest.raises(NotFoundError):
                await service.get_conversation(
                    conv_id, user_id=uuid4(), organization_id=TEST_ORG_ID
                )

    @pytest.mark.anyio
    async def test_get_conversation_null_owner_allows_a_participant(
        self, service: ConversationService
    ):
        """The other half: somebody who spoke in the room may open it."""
        conv_id = uuid4()
        mock_conv = MockConversation(id=conv_id, user_id=None)

        with (
            patch("app.services.conversation.conversation_repo") as mock_repo,
            patch("app.services.conversation.conversation_share_repo") as mock_share_repo,
        ):
            mock_repo.get_conversation_by_id = AsyncMock(return_value=mock_conv)
            mock_share_repo.get_share = AsyncMock(return_value=None)
            mock_repo.spoke_in = AsyncMock(return_value=True)

            result = await service.get_conversation(
                conv_id, user_id=uuid4(), organization_id=TEST_ORG_ID
            )

            assert result.id == conv_id


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
            mock_repo.spoke_in = AsyncMock(return_value=False)

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
            mock_repo.spoke_in = AsyncMock(return_value=False)

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
            mock_repo.spoke_in = AsyncMock(return_value=False)

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
            mock_repo.count_messages = AsyncMock(return_value=2)

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
    """Tests for link_files_to_message."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db: AsyncMock) -> ConversationService:
        """Create ConversationService instance with mock db."""
        return ConversationService(mock_db)

    @pytest.mark.anyio
    async def test_link_files_empty_list_returns_early(self, service: ConversationService):
        """link_files_to_message returns immediately for empty file list."""
        await service.link_files_to_message(uuid4(), [])

        # Should not call db.execute for empty list
        service.db.execute.assert_not_called()

    @pytest.mark.anyio
    async def test_link_files_calls_db(self, service: ConversationService):
        """link_files_to_message executes update and flushes."""
        msg_id = uuid4()
        file_ids = [str(uuid4()), str(uuid4())]

        with (
            patch("app.db.models.chat_file.ChatFile") as mock_chat_file,
            patch("sqlalchemy.update") as mock_sa_update,
        ):
            mock_chat_file.id.in_ = MagicMock()
            mock_sa_update.return_value.where.return_value.values.return_value = "stmt"

            await service.link_files_to_message(msg_id, file_ids)

            service.db.execute.assert_called_once()
            service.db.flush.assert_called_once()
