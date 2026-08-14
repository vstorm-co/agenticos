"""Tests for organization scoping of agent sessions.

Covers the two halves of the WebSocket org boundary:
  - `get_active_organization_ws` - which org a socket runs as
  - `persist_user_turn` - which org a turn is written to, and the refusal to
    resume a conversation belonging to another org
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from fastapi import WebSocketException

from app.api.deps import get_active_organization_ws
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.services.agent import persist_user_turn
from app.services.conversation import ConversationService


def _org(org_id=None):
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    return org


def _user(user_id=None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    return user


@asynccontextmanager
async def _fake_db_context():
    db = MagicMock()
    db.refresh = AsyncMock()
    db.expunge = MagicMock()
    yield db


class TestActiveOrganizationWS:
    """Resolving the organization a WebSocket session runs as."""

    @pytest.mark.anyio
    async def test_falls_back_to_personal_org(self):
        """No organization_id parameter -> the user's Personal org."""
        user = _user()
        personal = _org()

        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch(
                "app.api.deps.organization_repo.get_personal_for_user",
                new=AsyncMock(return_value=personal),
            ),
        ):
            org = await get_active_organization_ws(user, organization_id=None)

        assert org.id == personal.id

    @pytest.mark.anyio
    async def test_missing_personal_org_closes_socket(self):
        """A user without a Personal org cannot open a session."""
        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch(
                "app.api.deps.organization_repo.get_personal_for_user",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(WebSocketException) as exc,
        ):
            await get_active_organization_ws(_user(), organization_id=None)

        assert exc.value.code == 4001

    @pytest.mark.anyio
    async def test_requested_org_returned_for_member(self):
        """A member gets the org they asked for, not their personal one."""
        requested = _org()

        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch("app.api.deps._member_repo.get", new=AsyncMock(return_value=MagicMock())),
            patch(
                "app.api.deps.organization_repo.get_by_id",
                new=AsyncMock(return_value=requested),
            ),
        ):
            org = await get_active_organization_ws(_user(), organization_id=requested.id)

        assert org.id == requested.id

    @pytest.mark.anyio
    async def test_non_member_is_rejected(self):
        """Asking for an org the user does not belong to closes the socket."""
        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch("app.api.deps._member_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(WebSocketException) as exc,
        ):
            await get_active_organization_ws(_user(), organization_id=uuid.uuid4())

        assert exc.value.code == 4003

    @pytest.mark.anyio
    async def test_unknown_org_looks_like_denied_access(self):
        """A non-existent org must not be distinguishable from a forbidden one."""
        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch("app.api.deps._member_repo.get", new=AsyncMock(return_value=MagicMock())),
            patch("app.api.deps.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
            pytest.raises(WebSocketException) as exc,
        ):
            await get_active_organization_ws(_user(), organization_id=uuid.uuid4())

        assert exc.value.code == 4003
        assert exc.value.reason == "Organization access denied"


class TestPersistUserTurnOrgScope:
    """Which organization a turn is written to."""

    def _conv_service(self, conversation=None):
        """A stand-in that refuses a call the real service would refuse.

        `create_autospec`, not `MagicMock`: the bare mock accepts any signature,
        so it answered happily while the real `get_conversation` raised
        `TypeError` for a missing `organization_id` - which is why the suite was
        green through #5 and every resumed turn was being dropped.
        """
        service = create_autospec(ConversationService, instance=True)
        service.get_conversation.return_value = conversation
        service.create_conversation.return_value = conversation
        service.add_message.return_value = MagicMock(id=uuid.uuid4())
        return service

    @pytest.mark.anyio
    async def test_new_conversation_stamped_with_active_org(self):
        """A new conversation belongs to the session's org, not the personal one."""
        org_id = uuid.uuid4()
        created = MagicMock(id=uuid.uuid4())
        service = self._conv_service(created)

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            prompt = await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=None,
                current_conversation_id=None,
                organization_id=org_id,
            )

        assert prompt.newly_created is True
        assert prompt.conversation_id == str(created.id)
        assert service.create_conversation.call_args.args[0].organization_id == org_id

    @pytest.mark.anyio
    async def test_a_resumed_conversation_persists_the_user_message(self):
        """The second message of a thread is written, not logged and dropped.

        This is #5 and it failed before the fix: `get_conversation` was called
        without `organization_id`, which it takes keyword-only and required, so
        the `TypeError` reached the `except` below `add_message` and every turn
        after the first vanished with a one-line warning. The frontend sends
        `conversation_id` on every frame from the second message onward, so this
        was the normal path.
        """
        org_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        conv = MagicMock(organization_id=org_id, title="Existing")
        service = self._conv_service(conv)

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            prompt = await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=str(conversation_id),
                current_conversation_id=None,
                organization_id=org_id,
            )

        service.add_message.assert_awaited_once()
        assert prompt.newly_created is False
        assert prompt.conversation_id == str(conversation_id)
        # The row the prompt landed in, so the caller can link it to the run that
        # does not exist yet. Without it the question is unreachable from run
        # history and only the answer is.
        assert prompt.message_id == service.add_message.return_value.id

    @pytest.mark.anyio
    async def test_the_conversation_is_resolved_against_the_active_org(self):
        """The tenant reaches the service, which is where the check lives."""
        org_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        service = self._conv_service(MagicMock(organization_id=org_id, title=None))

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=str(conversation_id),
                current_conversation_id=None,
                organization_id=org_id,
            )

        assert service.get_conversation.await_args.kwargs["organization_id"] == org_id
        # The retitling of an untitled thread goes through the same door, and it
        # was the second call #5 named.
        assert service.update_conversation.await_args.kwargs["organization_id"] == org_id

    @pytest.mark.anyio
    async def test_a_conversation_outside_the_active_org_is_refused(self):
        """Owning the conversation is not enough - it must be in the active org.

        The service reports another tenant's row as missing, so that is what this
        stands in for; the refusal itself is asserted against a real service and
        a real database in `tests/integration/test_conversation_tenant_isolation.py`.
        """
        service = self._conv_service()
        service.get_conversation.side_effect = NotFoundError(message="Conversation not found")

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
            pytest.raises(AuthorizationError),
        ):
            await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=str(uuid.uuid4()),
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
            )

        service.add_message.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_id_that_is_not_a_uuid_is_refused_rather_than_swallowed(self):
        """Malformed input from the socket is a refusal, not a lost message."""
        service = self._conv_service()

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
            pytest.raises(BadRequestError),
        ):
            await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id="not-a-uuid",
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
            )

        service.add_message.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_database_failure_is_the_only_thing_still_swallowed(self):
        """A lost message must not abort a turn - but only for that reason.

        A `TypeError` used to take this path and read as a transient failure,
        which is the whole of #5.
        """
        from sqlalchemy.exc import OperationalError

        service = self._conv_service(MagicMock(organization_id=uuid.uuid4(), title="Existing"))
        service.add_message.side_effect = OperationalError("SELECT 1", {}, Exception("gone"))

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            prompt = await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=None,
                current_conversation_id=str(uuid.uuid4()),
                organization_id=uuid.uuid4(),
            )

        assert prompt.message_id is None

    @pytest.mark.anyio
    async def test_a_signature_that_no_longer_binds_is_not_swallowed(self):
        """The defect #5 was: it must reach the caller rather than a log line."""
        service = self._conv_service(MagicMock(organization_id=uuid.uuid4(), title="Existing"))
        service.add_message.side_effect = TypeError("missing a required keyword-only argument")

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
            pytest.raises(TypeError),
        ):
            await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=None,
                current_conversation_id=str(uuid.uuid4()),
                organization_id=uuid.uuid4(),
            )


class TestPersistUserTurnFileLinks:
    """A turn's files are linked as the caller, and a refusal aborts the turn (#706)."""

    def _conv_service(self):
        service = create_autospec(ConversationService, instance=True)
        service.create_conversation.return_value = MagicMock(id=uuid.uuid4())
        service.add_message.return_value = MagicMock(id=uuid.uuid4())
        return service

    @pytest.mark.anyio
    async def test_files_are_linked_as_the_caller(self):
        """`user_id` is the only scope a `chat_files` row has, so the link has to
        carry who is asking."""
        user = _user()
        service = self._conv_service()
        file_id = str(uuid.uuid4())

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            prompt = await persist_user_turn(
                user,
                "look at this",
                [file_id],
                requested_conversation_id=None,
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
            )

        linked = service.link_files_to_message.await_args
        assert linked.args == (service.add_message.return_value.id, [file_id])
        assert linked.kwargs == {"user_id": user.id}
        assert prompt.message_id == service.add_message.return_value.id

    @pytest.mark.anyio
    async def test_a_refused_file_aborts_the_turn(self):
        """The refusal used to be swallowed by the same net that catches a lost
        connection, so a turn naming somebody else's file went ahead and answered
        as though the attachment were fine (#706)."""
        service = self._conv_service()
        service.link_files_to_message.side_effect = NotFoundError(
            message="File not found", details={"file_ids": []}
        )

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
            pytest.raises(NotFoundError),
        ):
            await persist_user_turn(
                _user(),
                "look at this",
                [str(uuid.uuid4())],
                requested_conversation_id=None,
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
            )

    @pytest.mark.anyio
    async def test_a_transient_link_failure_still_answers_the_turn(self):
        """The swallow the refusal now escapes is kept for what it was written
        for: an infrastructure failure loses the link, never the answer."""
        service = self._conv_service()
        service.link_files_to_message.side_effect = RuntimeError("connection lost")

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            prompt = await persist_user_turn(
                _user(),
                "look at this",
                [str(uuid.uuid4())],
                requested_conversation_id=None,
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
            )

        assert prompt.message_id == service.add_message.return_value.id


class TestPersistAssistantTurnRecordsWhatItCost:
    """The cost of an answer is asked about afterwards.

    It used to live in the `complete` frame alone, so it existed for exactly as long
    as the tab did: a reopened conversation showed no cost under the input and none
    under any message, and the numbers came back only after sending something new.
    """

    def _conv_service(self):
        service = MagicMock()
        service.add_message = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        service.start_tool_call = AsyncMock()
        return service

    @pytest.mark.anyio
    async def test_the_split_and_the_money_are_written_to_the_message(self):
        from decimal import Decimal

        from app.services.agent import persist_assistant_turn
        from app.services.usage_report import UsageReport

        service = self._conv_service()

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            await persist_assistant_turn(
                str(uuid.uuid4()),
                "answered",
                "gpt-4.1",
                [],
                organization_id=uuid.uuid4(),
                usage=UsageReport(input_tokens=1200, output_tokens=300, cost_usd=Decimal("0.0125")),
            )

        written = service.add_message.await_args.kwargs["data"]
        assert (written.input_tokens, written.output_tokens) == (1200, 300)
        assert written.cost_usd == Decimal("0.0125")

    @pytest.mark.anyio
    async def test_a_turn_nobody_could_measure_records_nothing_rather_than_zero(self):
        """Null reads back as "not recorded". Zeroes would say the answer was free."""
        from app.services.agent import persist_assistant_turn

        service = self._conv_service()

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.get_conversation_service", return_value=service),
        ):
            await persist_assistant_turn(
                str(uuid.uuid4()), "answered", None, [], organization_id=uuid.uuid4()
            )

        written = service.add_message.await_args.kwargs["data"]
        assert (written.input_tokens, written.output_tokens, written.cost_usd) == (
            None,
            None,
            None,
        )
