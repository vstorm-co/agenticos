"""A number is kept only for people with no account: linking drops it (#2076)."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channel_link import ChannelLinkService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

ORG = uuid.uuid4()
USER = uuid.uuid4()
MODULE = "app.services.channel_link"


def _identity(platform: str = "whatsapp") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), platform=platform, platform_user_id=f"{ORG}:US.111", user_id=None
    )


def _request(platform: str = "whatsapp") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), platform=platform, platform_user_id=f"{ORG}:US.111",
        platform_username=None, platform_display_name=None, confirmed_user_id=USER,
        confirm_code="123456", expires_at=datetime.max.replace(tzinfo=UTC),
    )  # fmt: skip


def _patches(identity: SimpleNamespace):
    clear = AsyncMock()
    stack = (
        patch(f"{MODULE}.channel_identity_repo.get_or_create", AsyncMock(return_value=identity)),
        patch(f"{MODULE}.channel_identity_repo.update", AsyncMock()),
        patch(f"{MODULE}.message_rating_repo.adopt_channel_ratings", AsyncMock()),
        patch(f"{MODULE}.whatsapp_customer_repo.clear_phone", clear),
    )
    return clear, stack


async def _within(stack, body):
    from contextlib import ExitStack

    with ExitStack() as exits:
        for each in stack:
            exits.enter_context(each)
        return await body()


async def test_linking_through_a_browser_confirmation_clears_the_number():
    identity = _identity()
    clear, stack = _patches(identity)

    await _within(stack, lambda: ChannelLinkService(MagicMock())._link(_request(), USER))

    assert clear.await_args.kwargs == {"organization_id": ORG, "bsuid": "US.111"}


async def test_linking_with_the_code_sent_back_clears_the_number():
    identity = _identity()
    clear, stack = _patches(identity)
    request = _request()
    incoming = SimpleNamespace(
        platform="whatsapp", platform_user_id=request.platform_user_id, text="123456"
    )
    extra = (
        patch(
            f"{MODULE}.channel_link_request_repo.get_for_identity", AsyncMock(return_value=request)
        ),
        patch(f"{MODULE}.channel_link_request_repo.delete_by_id", AsyncMock(return_value=True)),
    )

    outcome = await _within(
        (*stack, *extra), lambda: ChannelLinkService(MagicMock()).complete_with_code(incoming)
    )

    assert outcome == "linked"
    clear.assert_awaited_once()


async def test_a_directory_vouched_link_clears_the_number():
    identity = _identity()
    clear, stack = _patches(identity)
    user = SimpleNamespace(id=USER, is_active=True, oauth_provider="oidc")
    extra = (patch(f"{MODULE}.user_repo.get_by_email", AsyncMock(return_value=user)),)

    linked = await _within(
        (*stack, *extra),
        lambda: ChannelLinkService(MagicMock()).link_vouched(identity, "a@example.com"),
    )

    assert linked is True
    assert clear.await_args.kwargs == {"organization_id": ORG, "bsuid": "US.111"}


async def test_another_platforms_link_clears_nothing():
    identity = _identity("slack")
    clear, stack = _patches(identity)

    await _within(stack, lambda: ChannelLinkService(MagicMock())._link(_request("slack"), USER))

    clear.assert_not_awaited()
