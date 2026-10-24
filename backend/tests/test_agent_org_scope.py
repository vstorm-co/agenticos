"""Tests for organization scoping of agent sessions.

Covers the two halves of the WebSocket org boundary:
  - `get_active_organization_ws` - which org a socket runs as
  - `persist_user_turn` - which org a turn is written to, and the refusal to
    resume a conversation belonging to another org
"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from fastapi import WebSocketException

from app.api.deps import get_active_organization, get_active_organization_ws
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.schemas.conversation import MessageReplyRef
from app.services.agent import persist_user_turn
from app.services.api_key import KeyCaller
from app.services.conversation import ConversationService


def _org(org_id=None):
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    return org


def _user(user_id=None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    return user


def _session_socket():
    """A socket opened with a session token: nothing about a key on its state."""
    socket = MagicMock()
    socket.state = SimpleNamespace()
    return socket


def _key_socket(organization):
    socket = MagicMock()
    socket.state = SimpleNamespace(
        api_key_caller=KeyCaller(
            user=_user(),
            organization=organization,
            context=MagicMock(),
            api_key_id=uuid.uuid4(),
            prefix="aos_0123abcd",
        )
    )
    return socket


@asynccontextmanager
async def _fake_db_context():
    db = MagicMock()
    db.refresh = AsyncMock()
    db.expunge = MagicMock()
    yield db


class TestActiveOrganizationHTTP:
    """A session request with no `X-Organization-Id` (#2156)."""

    @pytest.mark.anyio
    async def test_it_acts_where_a_session_lands(self):
        landing = _org()
        request = MagicMock(state=SimpleNamespace())

        with patch(
            "app.api.deps.OrganizationService.fallback_for", new=AsyncMock(return_value=landing)
        ):
            org = await get_active_organization(request, _user(), MagicMock(), None)

        assert org is landing

    @pytest.mark.anyio
    @pytest.mark.security
    async def test_a_user_with_a_choice_is_asked_for_the_header(self):
        """Guessing would be a script that forgot the header quietly acting in
        another tenant."""
        request = MagicMock(state=SimpleNamespace())

        with (
            patch(
                "app.api.deps.OrganizationService.fallback_for", new=AsyncMock(return_value=None)
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await get_active_organization(request, _user(), MagicMock(), None)

        assert refused.value.details == {"header": "X-Organization-Id"}


class TestActiveOrganizationWS:
    """Resolving the organization a WebSocket session runs as."""

    @pytest.mark.anyio
    async def test_a_key_socket_runs_in_the_key_s_organization(self):
        """An organization key carries its organization, so the socket needs no
        parameter and no membership read to know where it acts (#1794)."""
        acme = _org()

        org = await get_active_organization_ws(_key_socket(acme), _user(), organization_id=None)

        assert org is acme

    @pytest.mark.anyio
    @pytest.mark.security
    async def test_a_key_socket_naming_another_organization_is_refused(self):
        with pytest.raises(WebSocketException) as refused:
            await get_active_organization_ws(
                _key_socket(_org()), _user(), organization_id=uuid.uuid4()
            )

        assert refused.value.code == 4003

    @pytest.mark.anyio
    async def test_falls_back_to_the_organization_a_session_lands_in(self):
        """No organization_id parameter -> where a request naming none acts (#2156)."""
        user = _user()
        personal = _org()

        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch(
                "app.api.deps.OrganizationService.fallback_for",
                new=AsyncMock(return_value=personal),
            ),
        ):
            org = await get_active_organization_ws(_session_socket(), user, organization_id=None)

        assert org.id == personal.id

    @pytest.mark.anyio
    async def test_a_user_with_a_choice_must_name_the_organization(self):
        """No fallback - two organizations, neither default nor personal - closes the socket."""
        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch(
                "app.api.deps.OrganizationService.fallback_for",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(WebSocketException) as exc,
        ):
            await get_active_organization_ws(_session_socket(), _user(), organization_id=None)

        assert exc.value.code == 4001

    @pytest.mark.anyio
    async def test_requested_org_returned_for_member(self):
        """A member gets the org they asked for, not their personal one."""
        requested = _org()

        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch(
                "app.api.deps._member_repo.get_with_organization",
                new=AsyncMock(return_value=(MagicMock(), requested)),
            ),
        ):
            org = await get_active_organization_ws(
                _session_socket(), _user(), organization_id=requested.id
            )

        assert org.id == requested.id

    @pytest.mark.anyio
    async def test_non_member_is_rejected(self):
        """Asking for an org the user does not belong to closes the socket."""
        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch(
                "app.api.deps._member_repo.get_with_organization",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(WebSocketException) as exc,
        ):
            await get_active_organization_ws(
                _session_socket(), _user(), organization_id=uuid.uuid4()
            )

        assert exc.value.code == 4003

    @pytest.mark.anyio
    async def test_a_refusal_names_no_organization(self):
        """A missing org and a forbidden one are one answer, so ids cannot be probed."""
        with (
            patch("app.api.deps.get_db_context", _fake_db_context),
            patch(
                "app.api.deps._member_repo.get_with_organization",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(WebSocketException) as exc,
        ):
            await get_active_organization_ws(
                _session_socket(), _user(), organization_id=uuid.uuid4()
            )

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
            patch("app.services.agent.ConversationService", return_value=service),
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
    async def test_a_new_conversation_starts_in_the_project_its_author_may_work_in(self):
        org_id, project_id = uuid.uuid4(), uuid.uuid4()
        service = self._conv_service(MagicMock(id=uuid.uuid4()))
        allowed = AsyncMock(return_value=MagicMock(id=project_id))

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.ConversationService", return_value=service),
            patch(
                "app.services.agent.member_repo.get",
                new=AsyncMock(return_value=MagicMock(role="member")),
            ),
            patch("app.services.agent.ProjectService.check_can_start", new=allowed),
        ):
            await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=None,
                current_conversation_id=None,
                organization_id=org_id,
                project_id=str(project_id),
            )

        assert service.create_conversation.call_args.args[0].project_id == project_id
        checked_as, checked_project = allowed.await_args.args
        assert (checked_as.organization_id, checked_as.role) == (org_id, "member")
        assert checked_project == project_id

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("project_id", "membership", "refusal"),
        [
            ("not-a-uuid", MagicMock(role="member"), BadRequestError),
            (str(uuid.uuid4()), None, AuthorizationError),
        ],
        # Named, not derived from the values: a random id in a test's name
        # differs between xdist workers, which then refuse to run at all.
        ids=["not-an-id", "not-a-member"],
    )
    async def test_a_project_that_cannot_be_started_in_starts_no_conversation(
        self, project_id, membership, refusal
    ):
        service = self._conv_service(MagicMock(id=uuid.uuid4()))

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.ConversationService", return_value=service),
            patch("app.services.agent.member_repo.get", new=AsyncMock(return_value=membership)),
            pytest.raises(refusal),
        ):
            await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=None,
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
                project_id=project_id,
            )

        service.create_conversation.assert_not_called()

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
            patch("app.services.agent.ConversationService", return_value=service),
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
        owner = _user()
        service = self._conv_service(
            MagicMock(organization_id=org_id, title=None, user_id=owner.id)
        )

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.ConversationService", return_value=service),
        ):
            await persist_user_turn(
                owner,
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
    async def test_a_reply_is_written_with_its_message_and_read_as_the_model_hears_it(self):
        """The text the model is handed is the turn as said - who, and to what -
        while the transcript keeps what was typed."""
        owner = _user()
        replied = uuid.uuid4()
        service = self._conv_service(
            MagicMock(organization_id=uuid.uuid4(), title="Plan", user_id=owner.id)
        )
        service.model_text.return_value = 'Kacper: (In reply to your earlier answer: "x")\n\nyes'
        quote = MessageReplyRef(message_id=replied, role="assistant", excerpt="x")
        service.reply_quoted.return_value = quote

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.ConversationService", return_value=service),
        ):
            prompt = await persist_user_turn(
                owner,
                "yes",
                [],
                requested_conversation_id=str(uuid.uuid4()),
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
                reply_to=str(replied),
            )

        written = service.add_message.await_args.args[1]
        assert (written.content, written.reply_to_message_id) == ("yes", replied)
        assert prompt.for_model is not None and prompt.for_model.endswith("yes")
        # For the teammates following the turn live, who have no transcript yet.
        assert prompt.reply == quote

    @pytest.mark.anyio
    async def test_a_turn_said_as_typed_hands_the_model_nothing_extra(self):
        service = self._conv_service(MagicMock(organization_id=uuid.uuid4(), title="t"))
        service.model_text.return_value = "hello"
        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.ConversationService", return_value=service),
        ):
            prompt = await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=None,
                current_conversation_id=str(uuid.uuid4()),
                organization_id=uuid.uuid4(),
            )
        assert prompt.for_model is None

    @pytest.mark.anyio
    async def test_the_sockets_own_project_thread_still_says_who_is_speaking(self):
        """A frame that names no thread continues the socket's own; in a project's
        chat that turn reached the model with no name, so the agent could not tell
        the people in it apart."""
        thread = uuid.uuid4()
        conversation = MagicMock(organization_id=uuid.uuid4(), project_id=uuid.uuid4())
        service = self._conv_service()
        service.find_conversation.return_value = conversation
        service.model_text.return_value = "Anna: hello"
        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.ConversationService", return_value=service),
        ):
            prompt = await persist_user_turn(
                _user(),
                "hello",
                [],
                requested_conversation_id=None,
                current_conversation_id=str(thread),
                organization_id=uuid.uuid4(),
            )
        service.find_conversation.assert_awaited_once_with(thread)
        assert service.model_text.await_args.args[1] is conversation
        assert prompt.for_model == "Anna: hello"

    @pytest.mark.anyio
    async def test_a_reply_to_something_that_is_not_a_message_id_is_refused(self):
        with pytest.raises(BadRequestError, match="not a message id"):
            await persist_user_turn(
                _user(),
                "yes",
                [],
                requested_conversation_id=None,
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
                reply_to="not-an-id",
            )

    @pytest.mark.anyio
    async def test_a_teammate_continuing_a_project_chat_does_not_rename_it(self):
        """Naming the thread stays its owner's, so a teammate's first words in an
        untitled project chat are a turn and not a new title."""
        service = self._conv_service(
            MagicMock(organization_id=uuid.uuid4(), title=None, user_id=uuid.uuid4())
        )

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.ConversationService", return_value=service),
        ):
            await persist_user_turn(
                _user(),
                "picking this up",
                [],
                requested_conversation_id=str(uuid.uuid4()),
                current_conversation_id=None,
                organization_id=uuid.uuid4(),
            )

        service.update_conversation.assert_not_awaited()
        service.add_message.assert_awaited_once()

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
            patch("app.services.agent.ConversationService", return_value=service),
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
            patch("app.services.agent.ConversationService", return_value=service),
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
            patch("app.services.agent.ConversationService", return_value=service),
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
            patch("app.services.agent.ConversationService", return_value=service),
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
            patch("app.services.agent.ConversationService", return_value=service),
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
            patch("app.services.agent.ConversationService", return_value=service),
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
            patch("app.services.agent.ConversationService", return_value=service),
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
            patch("app.services.agent.ConversationService", return_value=service),
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
    async def test_a_call_an_organization_server_served_is_stored_against_it(self):
        """What a server's call log reads (#2072); a tool no organization
        connection served is stored against none."""
        from app.services.agent import persist_assistant_turn

        service = self._conv_service()
        linear = uuid.uuid4()

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.ConversationService", return_value=service),
        ):
            await persist_assistant_turn(
                str(uuid.uuid4()),
                "answered",
                None,
                [
                    {"tool_call_id": "c1", "tool_name": "linear_search", "args": {}},
                    {"tool_call_id": "c2", "tool_name": "web_search", "args": {}},
                ],
                organization_id=uuid.uuid4(),
                mcp_origins={"linear_search": linear},
            )

        assert [
            call.kwargs["mcp_connection_id"] for call in service.start_tool_call.await_args_list
        ] == [linear, None]

    @pytest.mark.anyio
    async def test_a_turn_nobody_could_measure_records_nothing_rather_than_zero(self):
        """Null reads back as "not recorded". Zeroes would say the answer was free."""
        from app.services.agent import persist_assistant_turn

        service = self._conv_service()

        with (
            patch("app.services.agent.get_db_context", _fake_db_context),
            patch("app.services.agent.ConversationService", return_value=service),
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


@pytest.mark.anyio
@pytest.mark.parametrize("status", [None, "awaiting_approval", "cancelled"])
async def test_a_late_parked_transcript_observes_a_stop_before_writing_calls(status):
    from app.repositories.conversation import Attributed
    from app.services.agent import persist_assistant_turn

    service = TestPersistAssistantTurnRecordsWhatItCost()._conv_service()
    service.complete_tool_call = AsyncMock()
    service.start_tool_call.return_value = MagicMock(id=uuid.uuid4())
    run_id, organization_id = uuid.uuid4(), uuid.uuid4()
    with (
        patch("app.services.agent.get_db_context", _fake_db_context),
        patch("app.services.agent.ConversationService", return_value=service),
        patch(
            "app.services.agent.conversation_repo.attributed_to_run",
            AsyncMock(return_value=Attributed()),
        ),
        patch(
            "app.services.agent.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=None if status is None else MagicMock(status=status)),
        ) as claim,
    ):
        saved = await persist_assistant_turn(
            str(uuid.uuid4()),
            "",
            None,
            [{"tool_call_id": "parked", "tool_name": "send_email", "args": {}}],
            organization_id=organization_id,
            run_id=run_id,
            parked_tool_call_ids={"parked"},
        )
    assert saved is not None
    assert claim.await_args.args[1] == run_id
    assert claim.await_args.kwargs["organization_id"] == organization_id
    assert service.start_tool_call.await_args.kwargs["parked"] is (status != "cancelled")
    if status == "cancelled":
        assert (
            service.complete_tool_call.await_args.args[1].result
            == "Not performed: the run was stopped."
        )
    else:
        service.complete_tool_call.assert_not_awaited()
