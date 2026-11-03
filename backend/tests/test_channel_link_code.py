"""Two-way confirmation of a chat-account link (#2076).

A phone number is shared, forwarded and recycled, so a click in a browser alone
must not link a WhatsApp chat: confirming issues a short code, and only the same
chat sending it back completes the link. The behaviour hangs on the request's
state and on `CODE_CONFIRMED_PLATFORMS`, never on a platform name in shared code.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError
from app.services import impersonation as impersonation_service
from app.services.channel_link import (
    AWAITING_CODE,
    CODE_TTL,
    LINK_CONFIRMED,
    ChannelLinkService,
)
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter
from app.services.channels.webhooks import CODE_CONFIRMED_PLATFORMS
from app.services.impersonation import ActiveImpersonation

pytestmark = pytest.mark.anyio

REPO = "app.services.channel_link.channel_link_request_repo"
USER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()


def _incoming(text: str = "hej", user: str = "org:bsuid-1") -> IncomingMessage:
    return IncomingMessage(
        platform="whatsapp",
        bot_id=str(uuid.uuid4()),
        platform_user_id=user,
        platform_chat_id="bsuid-1",
        chat_type="private",
        text=text,
        raw={},
        platform_username="•••• 1234",
        platform_display_name="Kacper",
    )


def _request(**overrides) -> MagicMock:
    request = MagicMock()
    request.id = uuid.uuid4()
    request.token = "tok"
    request.platform = "whatsapp"
    request.platform_user_id = "org:bsuid-1"
    request.platform_username = "•••• 1234"
    request.platform_display_name = "Kacper"
    request.expires_at = datetime.now(UTC) + timedelta(minutes=5)
    request.confirmed_user_id = None
    request.confirm_code = None
    for key, value in overrides.items():
        setattr(request, key, value)
    return request


def _awaiting(code: str = "123456", **overrides) -> MagicMock:
    return _request(confirmed_user_id=USER_ID, confirm_code=code, **overrides)


def _db() -> MagicMock:
    db = MagicMock()
    db.refresh = AsyncMock()
    return db


def test_whatsapp_is_the_platform_that_confirms_twice():
    assert frozenset({"whatsapp"}) == CODE_CONFIRMED_PLATFORMS


class TestConfirmingIssuesACode:
    async def test_confirming_a_whatsapp_link_issues_a_code_and_links_nothing(self):
        request = _request()
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock(return_value=request)),
            patch(f"{REPO}.claim_for_code", new=AsyncMock(return_value=True)) as claim,
            patch(f"{REPO}.delete_by_id", new=AsyncMock()) as spent,
            patch(
                "app.services.channel_link.channel_identity_repo.get_or_create",
                new=AsyncMock(),
            ) as resolved,
            patch(
                "app.services.channel_link.channel_identity_repo.update", new=AsyncMock()
            ) as updated,
        ):
            before = datetime.now(UTC)
            result = await ChannelLinkService(_db()).confirm("tok", USER_ID)

        assert result is request
        kwargs = claim.call_args.kwargs
        assert kwargs["request_id"] == request.id
        assert kwargs["user_id"] == USER_ID
        assert len(kwargs["code"]) == 6 and kwargs["code"].isdigit()
        assert before + CODE_TTL <= kwargs["expires_at"] <= datetime.now(UTC) + CODE_TTL
        spent.assert_not_awaited()
        resolved.assert_not_awaited()
        updated.assert_not_awaited()

    async def test_a_lost_claim_gives_no_code(self):
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock(return_value=_request())),
            patch(f"{REPO}.claim_for_code", new=AsyncMock(return_value=False)),
        ):
            assert await ChannelLinkService(_db()).confirm("tok", USER_ID) is None

    async def test_a_lost_claim_to_the_same_user_gets_the_winners_code(self):
        request = _request()
        winner = _awaiting("654321")
        db = _db()
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock(side_effect=[request, winner])),
            patch(f"{REPO}.claim_for_code", new=AsyncMock(return_value=False)),
        ):
            result = await ChannelLinkService(db).confirm("tok", USER_ID)

        assert result is winner
        assert result.confirm_code == "654321"
        db.expire.assert_called_once_with(request)
        db.refresh.assert_not_awaited()

    async def test_a_lost_claim_to_another_user_still_gives_nothing(self):
        other = _request(confirmed_user_id=uuid.uuid4(), confirm_code="654321")
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock(side_effect=[_request(), other])),
            patch(f"{REPO}.claim_for_code", new=AsyncMock(return_value=False)),
        ):
            assert await ChannelLinkService(_db()).confirm("tok", USER_ID) is None

    async def test_a_lost_claim_whose_request_is_gone_gives_nothing(self):
        """The chat side can delete the request while the confirm waits on the row lock."""
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock(side_effect=[_request(), None])),
            patch(f"{REPO}.claim_for_code", new=AsyncMock(return_value=False)),
        ):
            assert await ChannelLinkService(_db()).confirm("tok", USER_ID) is None

    async def test_an_unknown_token_issues_nothing(self):
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock(return_value=None)),
            patch(f"{REPO}.claim_for_code", new=AsyncMock()) as claim,
        ):
            assert await ChannelLinkService(_db()).confirm("tok", USER_ID) is None
        claim.assert_not_awaited()

    async def test_another_user_cannot_read_or_confirm_a_request_awaiting_someone_elses_code(
        self,
    ):
        awaiting = _awaiting()
        service = ChannelLinkService(_db())
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock(return_value=awaiting)),
            patch(f"{REPO}.claim_for_code", new=AsyncMock()) as claim,
        ):
            assert await service.pending("tok", OTHER_ID) is None
            assert await service.confirm("tok", OTHER_ID) is None
            # The one who confirmed can still read it, to see the code again.
            assert await service.pending("tok", USER_ID) is awaiting
        claim.assert_not_awaited()

    async def test_confirming_again_returns_the_same_code(self):
        """A second tab or a retried POST by the person who already confirmed."""
        awaiting = _awaiting("123456")
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock(return_value=awaiting)),
            patch(f"{REPO}.claim_for_code", new=AsyncMock()) as claim,
        ):
            result = await ChannelLinkService(_db()).confirm("tok", USER_ID)

        assert result is awaiting
        assert result.confirm_code == "123456"
        claim.assert_not_awaited()

    async def test_impersonation_is_refused_before_anything_else(self):
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock()) as read,
            patch(f"{REPO}.claim_for_code", new=AsyncMock()) as claim,
        ):
            active = impersonation_service._active.set(
                ActiveImpersonation(
                    session_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    impersonator_id=uuid.uuid4(),
                    expires_at=datetime(2099, 1, 1, tzinfo=UTC),
                )
            )
            try:
                with pytest.raises(AuthorizationError):
                    await ChannelLinkService(_db()).confirm("tok", USER_ID)
            finally:
                impersonation_service._active.reset(active)
        read.assert_not_awaited()
        claim.assert_not_awaited()

    async def test_telegram_links_exactly_as_before(self):
        request = _request(platform="telegram", platform_user_id="42")
        identity = MagicMock(id=uuid.uuid4(), user_id=None)
        with (
            patch(f"{REPO}.get_valid", new=AsyncMock(return_value=request)),
            patch(f"{REPO}.claim_for_code", new=AsyncMock()) as claim,
            patch(f"{REPO}.delete_by_id", new=AsyncMock(return_value=True)) as spent,
            patch(
                "app.services.channel_link.channel_identity_repo.get_or_create",
                new=AsyncMock(return_value=identity),
            ),
            patch(
                "app.services.channel_link.channel_identity_repo.update", new=AsyncMock()
            ) as updated,
            patch(
                "app.services.channel_link.message_rating_repo.adopt_channel_ratings",
                new=AsyncMock(),
            ),
        ):
            result = await ChannelLinkService(_db()).confirm("tok", USER_ID)

        assert result is request
        claim.assert_not_awaited()
        spent.assert_awaited_once()
        assert updated.call_args.kwargs["update_data"] == {"user_id": USER_ID}


class TestSendingTheCode:
    async def _complete(self, request: MagicMock | None, text: str, *, claimed: bool = True):
        identity = MagicMock(id=uuid.uuid4(), user_id=None)
        with (
            patch(f"{REPO}.get_for_identity", new=AsyncMock(return_value=request)),
            patch(f"{REPO}.delete_by_id", new=AsyncMock(return_value=claimed)) as spent,
            patch(f"{REPO}.delete_for_identity", new=AsyncMock()) as cleared,
            patch(
                "app.services.channel_link.channel_identity_repo.get_or_create",
                new=AsyncMock(return_value=identity),
            ) as resolved,
            patch(
                "app.services.channel_link.channel_identity_repo.update", new=AsyncMock()
            ) as updated,
            patch(
                "app.services.channel_link.message_rating_repo.adopt_channel_ratings",
                new=AsyncMock(),
            ) as adopted,
        ):
            outcome = await ChannelLinkService(_db()).complete_with_code(_incoming(text))
        self.spent, self.cleared, self.resolved = spent, cleared, resolved
        self.updated, self.adopted, self.identity = updated, adopted, identity
        return outcome

    async def test_the_code_sent_from_that_chat_completes_the_link(self):
        assert await self._complete(_awaiting(), " 123456\n") == "linked"
        self.spent.assert_awaited_once()
        assert self.resolved.call_args.kwargs["user_id"] == USER_ID
        assert self.updated.call_args.kwargs["update_data"] == {"user_id": USER_ID}
        self.adopted.assert_awaited_once_with(ANY, identity_id=self.identity.id, user_id=USER_ID)

    async def test_a_code_whose_claim_is_lost_links_nothing(self):
        assert await self._complete(_awaiting(), "123456", claimed=False) == "none"
        assert self.resolved.await_count == 0

    async def test_the_code_from_another_chat_does_nothing(self):
        """The lookup is keyed on the chat account: the right code from another
        chat finds no request, so nothing is linked or deleted."""
        awaiting = _awaiting("123456")

        async def by_identity(_db, *, platform: str, platform_user_id: str):
            return awaiting if platform_user_id == "org:bsuid-1" else None

        identity = MagicMock(id=uuid.uuid4(), user_id=None)
        with (
            patch(f"{REPO}.get_for_identity", new=AsyncMock(side_effect=by_identity)) as lookup,
            patch(f"{REPO}.delete_by_id", new=AsyncMock()) as spent,
            patch(f"{REPO}.delete_for_identity", new=AsyncMock()) as cleared,
            patch(
                "app.services.channel_link.channel_identity_repo.get_or_create",
                new=AsyncMock(return_value=identity),
            ) as resolved,
        ):
            outcome = await ChannelLinkService(_db()).complete_with_code(
                _incoming("123456", user="org:bsuid-2")
            )

        assert outcome == "none"
        assert lookup.call_args.kwargs["platform_user_id"] == "org:bsuid-2"
        resolved.assert_not_awaited()
        spent.assert_not_awaited()
        cleared.assert_not_awaited()

    async def test_a_request_nobody_confirmed_yet_is_not_a_code_request(self):
        assert await self._complete(_request(), "123456") == "none"
        assert self.resolved.await_count == 0

    async def test_a_wrong_six_digit_code_cancels_the_request(self):
        assert await self._complete(_awaiting(), "654321") == "none"
        self.cleared.assert_awaited_once()
        assert self.cleared.call_args.kwargs["platform_user_id"] == "org:bsuid-1"
        assert self.resolved.await_count == 0

    async def test_an_expired_code_does_nothing(self):
        expired = _awaiting(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        assert await self._complete(expired, "123456") == "none"
        assert self.resolved.await_count == 0

    async def test_other_text_awaits_and_keeps_the_request(self):
        assert await self._complete(_awaiting(), "hello there") == "awaiting"
        assert self.cleared.await_count == 0
        assert self.spent.await_count == 0

    async def test_text_that_is_not_ascii_cannot_crash_the_comparison(self):
        assert await self._complete(_awaiting(), "١٢٣٤٥٦") == "awaiting"


class TestTheRouterAnswers:
    async def _route(self, outcome: str, *, linked: bool = False, limited: bool = False):
        from app.core.exceptions import BadRequestError

        router = ChannelMessageRouter()
        bot = MagicMock(is_active=True, access_policy={})
        sent = AsyncMock()
        invite = AsyncMock(return_value="link first")
        handle = AsyncMock(return_value=None)
        check = AsyncMock(
            side_effect=BadRequestError(message="Rate limit exceeded. Please slow down.")
            if limited
            else None
        )
        with (
            patch(
                "app.services.channels.router.channel_bot_repo.get_for_inbound",
                new=AsyncMock(return_value=bot),
            ),
            patch.object(
                ChannelMessageRouter,
                "_resolve_identity",
                new=AsyncMock(return_value=MagicMock(user_id=USER_ID if linked else None)),
            ),
            patch.object(
                ChannelLinkService, "complete_with_code", new=AsyncMock(return_value=outcome)
            ),
            patch.object(ChannelMessageRouter, "_handle_command", new=handle),
            patch.object(
                ChannelMessageRouter, "_sender_is_active_member", new=AsyncMock(return_value=linked)
            ),
            patch.object(ChannelMessageRouter, "_check_rate_limit", new=check),
            patch.object(ChannelMessageRouter, "_invite_to_link", new=invite),
            patch.object(ChannelMessageRouter, "_send_reply", new=sent),
            patch.object(
                ChannelMessageRouter, "_resolve_session", new=AsyncMock(side_effect=RuntimeError)
            ),
        ):
            try:
                await router._route_inner(_incoming(), MagicMock())
            except RuntimeError:
                return sent, invite, handle, True
        return sent, invite, handle, False

    async def test_other_text_before_the_code_keeps_the_request_and_says_what_to_do(self):
        sent, invite, handle, proceeded = await self._route("awaiting")

        assert sent.await_args.args[2] == AWAITING_CODE
        invite.assert_not_awaited()  # it would delete the request
        handle.assert_not_awaited()
        assert not proceeded

    async def test_waiting_for_a_code_still_spends_the_senders_allowance(self):
        sent, invite, _, _ = await self._route("awaiting", limited=True)

        assert "slow down" in sent.await_args.args[2]
        invite.assert_not_awaited()

    async def test_the_router_answers_a_completed_link_and_runs_no_turn(self):
        sent, _, handle, proceeded = await self._route("linked")

        assert sent.await_args.args[2] == LINK_CONFIRMED
        handle.assert_not_awaited()
        assert not proceeded

    async def test_no_request_continues_as_today(self):
        sent, invite, _, _ = await self._route("none")

        invite.assert_awaited_once()
        assert sent.await_args.args[2] == "link first"

    async def test_an_already_linked_sender_is_not_held_up_by_a_stale_request(self):
        _, _, _, proceeded = await self._route("awaiting", linked=True)

        assert proceeded  # went on to resolve a session


class TestWhatThePageIsTold:
    async def _post(self, request: MagicMock, caller: uuid.UUID):
        from app.api.routes.v1.me_channel_link import confirm_link_request, read_link_request

        service = MagicMock(
            pending=AsyncMock(return_value=request), confirm=AsyncMock(return_value=request)
        )
        user = MagicMock(id=caller)
        return (
            await read_link_request("tok", service, user),
            await confirm_link_request("tok", service, user),
        )

    async def test_the_confirmer_gets_the_code(self):
        for read in await self._post(_awaiting("123456"), USER_ID):
            assert read.awaiting_code is True
            assert read.confirm_code == "123456"
            assert read.display_name_verified is False

    async def test_nobody_but_the_confirmer_is_handed_the_code(self):
        read, _ = await self._post(_awaiting("123456"), OTHER_ID)
        assert read.awaiting_code is True
        assert read.confirm_code is None

    async def test_a_one_way_platform_has_no_code_and_a_verified_name(self):
        read, _ = await self._post(_request(platform="telegram"), USER_ID)
        assert read.awaiting_code is False
        assert read.confirm_code is None
        assert read.display_name_verified is True

    async def test_the_code_is_not_readable_under_an_impersonation(self):
        active = impersonation_service._active.set(
            ActiveImpersonation(
                session_id=uuid.uuid4(),
                user_id=USER_ID,
                impersonator_id=uuid.uuid4(),
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )
        try:
            reads = await self._post(_awaiting("123456"), USER_ID)
        finally:
            impersonation_service._active.reset(active)
        for read in reads:
            assert read.awaiting_code is True
            assert read.confirm_code is None

    async def test_a_gone_request_is_not_found(self):
        from app.api.routes.v1.me_channel_link import read_link_request
        from app.core.exceptions import NotFoundError

        service = MagicMock(pending=AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await read_link_request("tok", service, MagicMock(id=USER_ID))
