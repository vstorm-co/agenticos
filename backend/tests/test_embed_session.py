"""One visitor's turn on a public widget, and what the session refuses.

A widget is a URL with a model behind it and nobody signed in, so almost
everything here is a refusal: a frame that is not a message, a paste bomb, a
visitor asking faster than the operator allowed, a run the platform would not
start. None of them may close the socket, because the conversation goes with it.

The other half is identity. An anonymous visitor has no role, so the turn runs
as the member who published the widget - and as a `viewer` when that member has
left the organization, since their departure must not silently widen what a
public page can reach.

The frame shapes are asserted here rather than in `tests/test_embed_widget.py`,
which reads the script; this reads the server that answers it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.services.embed_session import MAX_MESSAGE_CHARS, EmbedSession, _buckets

pytestmark = pytest.mark.anyio

MODULE = "app.services.embed_session"


@pytest.fixture(autouse=True)
def _empty_buckets() -> Iterator[None]:
    """The rolling window is a module-level dict; a leftover count is another test's."""
    _buckets.clear()
    yield
    _buckets.clear()


def _embed(**overrides: Any) -> MagicMock:
    embed = MagicMock()
    embed.id = uuid.uuid4()
    embed.organization_id = uuid.uuid4()
    embed.agent_id = uuid.uuid4()
    embed.owner_user_id = uuid.uuid4()
    embed.name = "Support"
    embed.context = None
    embed.context_variables = []
    embed.rate_limit_per_minute = 10
    for key, value in overrides.items():
        setattr(embed, key, value)
    return embed


def _variable(name: str, *, required: bool = False) -> dict[str, Any]:
    return {"name": name, "required": required, "description": ""}


@pytest.fixture
def execute(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    run = AsyncMock(return_value=("Our pricing starts at $10.", MagicMock()))
    runner = MagicMock()
    runner.return_value.execute = run
    monkeypatch.setattr(f"{MODULE}.AgentRunnerService", runner)
    return run


@pytest.fixture
def create_conversation(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    monkeypatch.setattr(f"{MODULE}.conversation_repo.create_conversation", create)
    return create


@pytest.fixture
def membership(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    get = AsyncMock(return_value=MagicMock(role=OrgRoleName.BUILDER.value))
    monkeypatch.setattr(f"{MODULE}.member_repo.get", get)
    return get


OpenSession = Callable[..., EmbedSession]


@pytest.fixture
def open_session(
    execute: AsyncMock, create_conversation: AsyncMock, membership: AsyncMock
) -> OpenSession:
    def _open(embed: MagicMock | None = None, *, visitor: str | None = None) -> EmbedSession:
        return EmbedSession(
            db=MagicMock(),
            embed=embed if embed is not None else _embed(),
            visitor=visitor,
            websocket=AsyncMock(),
        )

    return _open


def _frames(session: EmbedSession) -> list[dict[str, Any]]:
    sent = cast(AsyncMock, session.websocket.send_json)
    return [call.args[0] for call in sent.await_args_list]


def _prompt_of(execute: AsyncMock) -> str:
    return execute.call_args.args[2]


def _context_of(execute: AsyncMock) -> AuthContext:
    return execute.call_args.args[0]


class TestWhatTheVisitorIsSent:
    async def test_a_visitor_with_no_token_is_greeted_as_anonymous(
        self, open_session: OpenSession
    ) -> None:
        session = open_session()

        await session.greet()

        assert _frames(session) == [{"type": "ready", "visitor": False}]

    async def test_a_visitor_the_page_signed_is_greeted_as_known(
        self, open_session: OpenSession
    ) -> None:
        """The widget draws itself differently for somebody it can name."""
        session = open_session(visitor="customer-7")

        await session.greet()

        assert _frames(session) == [{"type": "ready", "visitor": True}]

    async def test_an_answer_arrives_behind_a_typing_frame(self, open_session: OpenSession) -> None:
        session = open_session()

        await session.handle({"type": "message", "text": "what does it cost?"})

        assert _frames(session) == [
            {"type": "typing"},
            {"type": "message", "role": "assistant", "text": "Our pricing starts at $10."},
        ]

    async def test_a_run_that_answered_nothing_still_closes_the_turn(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        """A budget stop ends here: the runner records the status and returns an
        empty answer rather than raising, so the visitor is owed a frame that
        replaces the typing bubble instead of one that never arrives."""
        execute.return_value = ("", MagicMock())
        session = open_session()

        await session.handle({"type": "message", "text": "hello"})

        assert _frames(session)[-1] == {"type": "message", "role": "assistant", "text": "…"}

    async def test_the_socket_going_away_does_not_take_the_turn_with_it(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        """The visitor closed the tab mid-answer. There is nothing to recover and
        nobody to tell, and raising here would log a failure for a working turn."""
        session = open_session()
        session.websocket.send_json = AsyncMock(side_effect=RuntimeError("socket is closed"))

        await session.handle({"type": "message", "text": "hello"})

        assert execute.await_count == 1

    async def test_a_failure_the_route_caught_reaches_the_visitor_as_an_error(
        self, open_session: OpenSession
    ) -> None:
        session = open_session()

        await session.fail("Something went wrong. Please try again.")

        assert _frames(session) == [
            {"type": "error", "message": "Something went wrong. Please try again."}
        ]

    async def test_closing_a_session_mid_conversation_releases_nothing(
        self, open_session: OpenSession
    ) -> None:
        """The route closes in a `finally`, on every disconnect. The session owns
        no task and no client, so this must complete rather than raise."""
        session = open_session()
        await session.handle({"type": "message", "text": "hello"})

        await session.close()

        assert _frames(session)[-1]["type"] == "message"


class TestWhatTheTurnRefuses:
    async def test_a_frame_that_is_not_a_message_is_ignored(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        """A widget cached in somebody's browser may be older than this server.
        Refusing its frame would close the socket and take the conversation."""
        session = open_session()

        await session.handle({"type": "seen", "id": "42"})

        assert _frames(session) == []
        assert execute.await_count == 0

    async def test_a_message_with_no_text_is_not_a_turn(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        session = open_session()

        await session.handle({"type": "message", "text": "   "})

        assert _frames(session) == []
        assert execute.await_count == 0

    async def test_a_paste_bomb_is_refused_before_the_model_sees_it(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        """A public URL with a model behind it is somebody else's bill."""
        session = open_session()

        await session.handle({"type": "message", "text": "x" * (MAX_MESSAGE_CHARS + 1)})

        assert _frames(session) == [
            {"type": "error", "message": "That message is too long. Try a shorter one."}
        ]
        assert execute.await_count == 0

    async def test_a_visitor_past_their_allowance_is_told_they_are_too_quick(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        session = open_session(_embed(rate_limit_per_minute=1))

        await session.handle({"type": "message", "text": "first"})
        await session.handle({"type": "message", "text": "second"})

        assert execute.await_count == 1
        assert _frames(session)[-1] == {
            "type": "error",
            "message": "You are sending messages too quickly.",
        }

    async def test_a_refused_run_says_nothing_about_why(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        """The visitor is on somebody else's marketing page. What the platform
        refused - an archived agent, a deleted model profile - is the operator's
        to read in a log, not a stranger's to read in a bubble."""
        execute.side_effect = BadRequestError(
            message="Agent 'support' has no published version",
            details={"agent_id": str(uuid.uuid4())},
        )
        session = open_session()

        await session.handle({"type": "message", "text": "hello"})

        assert _frames(session)[-1] == {
            "type": "error",
            "message": "This assistant is unavailable.",
        }
        assert not any("published" in str(frame) for frame in _frames(session))


class TestWhatTheTurnRunsAs:
    async def test_a_turn_runs_as_the_member_who_published_the_widget(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        """A visitor has no role, and an agent needs one to resolve what it may
        reach. The publisher's is the only honest answer available."""
        embed = _embed()
        session = open_session(embed)

        await session.handle({"type": "message", "text": "hello"})

        ctx = _context_of(execute)
        assert ctx.user_id == embed.owner_user_id
        assert ctx.organization_id == embed.organization_id
        assert ctx.role == OrgRoleName.BUILDER.value

    async def test_an_owner_who_has_left_narrows_the_turn_to_a_viewer(
        self, open_session: OpenSession, execute: AsyncMock, membership: AsyncMock
    ) -> None:
        """Their departure must not silently widen what a public widget can do."""
        membership.return_value = None
        session = open_session()

        await session.handle({"type": "message", "text": "hello"})

        assert _context_of(execute).role == OrgRoleName.VIEWER.value

    async def test_a_widget_with_no_owner_runs_as_a_viewer(
        self, open_session: OpenSession, execute: AsyncMock, membership: AsyncMock
    ) -> None:
        """Nobody to look up: the owner's account is gone, and the widget is
        still on a page somewhere."""
        session = open_session(_embed(owner_user_id=None))

        await session.handle({"type": "message", "text": "hello"})

        assert membership.await_count == 0
        ctx = _context_of(execute)
        assert ctx.user_id is None
        assert ctx.role == OrgRoleName.VIEWER.value

    async def test_the_conversation_records_that_nobody_signed_in(
        self, open_session: OpenSession, create_conversation: AsyncMock
    ) -> None:
        """The publisher's role is what the run carries; the transcript still
        belongs to no user, which is the honest record of an anonymous visit."""
        embed = _embed()
        session = open_session(embed)

        await session.handle({"type": "message", "text": "hello"})

        assert create_conversation.call_args.kwargs["user_id"] is None
        assert create_conversation.call_args.kwargs["organization_id"] == embed.organization_id


class TestWhatThePageMaySupply:
    async def test_a_context_that_is_not_an_object_supplies_nothing(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        """The frame comes from a page a visitor can edit. A string where an
        object was expected is dropped, not coerced into a line of the block."""
        session = open_session(_embed(context_variables=[_variable("plan")]))

        await session.handle({"type": "message", "text": "hello", "context": "plan=admin"})

        assert _prompt_of(execute) == "hello"

    async def test_a_declared_value_nobody_promised_is_simply_absent(
        self, open_session: OpenSession, execute: AsyncMock
    ) -> None:
        """An optional variable the page did not send costs neither a warning
        nor a line saying it is missing - the block holds what arrived."""
        session = open_session(_embed(context_variables=[_variable("plan"), _variable("locale")]))

        await session.handle({"type": "message", "text": "hello", "context": {"plan": "pro"}})

        prompt = _prompt_of(execute)
        assert "plan: pro" in prompt
        assert "locale" not in prompt
