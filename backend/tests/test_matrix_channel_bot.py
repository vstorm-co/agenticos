"""A Matrix bot carries its homeserver and takes no webhook (#2081).

A homeserver is somebody's own server, as a Mattermost one is, so a bot that does
not know it can do nothing; and a homeserver has no outgoing webhook, so the bot
reads its `/sync` and a webhook setting would be stored and never used.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.db.models.agent_exposure import ExposureSurface
from app.db.models.agent_run import CHANNEL_SURFACES, RunSurface
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotUpdate
from app.services.channel_bot import ChannelBotService
from app.services.channels.formatting import HOUSE_STYLE, runtime_context

pytestmark = pytest.mark.anyio

HOMESERVER = "https://matrix.example.org"


def _row(**overrides: object) -> ChannelBot:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "platform": "matrix",
        "name": "bot",
        "token_encrypted": "",
        "secret_key_version": 1,
        "api_base_url": HOMESERVER,
    }
    values.update(overrides)
    return ChannelBot(**values)


def test_a_matrix_bot_is_created_with_its_token_and_homeserver():
    created = ChannelBotCreate(
        platform="matrix", name="bot", token="t" * 40, api_base_url=HOMESERVER
    )
    assert created.webhook_mode is False
    assert created.ack_reaction == "eyes"


def test_a_matrix_bot_without_its_homeserver_is_refused():
    with pytest.raises(ValidationError, match="server's URL"):
        ChannelBotCreate(platform="matrix", name="bot", token="t" * 40)


@pytest.mark.parametrize("webhook", [{"webhook_mode": True}, {"webhook_secret": "s" * 16}])
def test_a_matrix_bot_with_a_webhook_is_refused(webhook: dict[str, object]):
    with pytest.raises(ValidationError, match="takes no webhook"):
        ChannelBotCreate(
            platform="matrix", name="bot", token="t" * 40, api_base_url=HOMESERVER, **webhook
        )


async def test_a_matrix_bot_cannot_lose_its_homeserver():
    bot = _row()
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            new=AsyncMock(return_value=bot),
        ),
        patch("app.services.channel_bot.channel_bot_repo.update", new=AsyncMock()) as update,
        pytest.raises(BadRequestError) as refused,
    ):
        service = ChannelBotService(MagicMock(), organization_id=bot.organization_id)
        await service.update(bot.id, ChannelBotUpdate(api_base_url=None), MagicMock())
    assert refused.value.details["fields"][0]["field"] == "api_base_url"
    update.assert_not_awaited()


def test_matrix_is_a_surface_an_agent_can_be_exposed_on_and_a_run_can_come_from():
    assert ExposureSurface("matrix") is ExposureSurface.MATRIX
    assert RunSurface.MATRIX in CHANNEL_SURFACES


def test_the_agent_is_told_it_answers_in_matrix():
    assert "Matrix" in runtime_context("matrix", console_url="https://aos", linked_sender=False)
    assert "Markdown" in HOUSE_STYLE["matrix"]


@pytest.mark.parametrize(
    ("policy", "active", "admitted"),
    [
        ({"mode": "open"}, True, True),
        ({"mode": "whitelist", "whitelist": ["@ada:example.org"]}, True, True),
        ({"mode": "whitelist", "whitelist": ["@bob:example.org"]}, True, False),
        ({"mode": "open"}, False, False),
    ],
    ids=["open", "listed", "not-listed", "paused"],
)
async def test_an_invitation_is_admitted_as_a_message_from_the_inviter_would_be(
    policy: dict[str, object], active: bool, admitted: bool
):
    """An invitation can bring the bot nowhere a message from the same person could not reach it."""
    from contextlib import asynccontextmanager

    from app.services.channels import ingress

    bot = _row(access_policy=policy, is_active=active)

    @asynccontextmanager
    async def session():
        yield MagicMock()

    with (
        patch.object(ingress, "get_db_context", session),
        patch.object(ingress.channel_bot_repo, "get_for_inbound", AsyncMock(return_value=bot)),
    ):
        assert (
            await ingress.invite_admitted(
                str(bot.id), "@ada:example.org", "%21room%3Aexample.org", direct=False
            )
            is admitted
        )


def test_history_filters_accept_native_matrix_user_identifiers() -> None:
    from app.agents.capabilities.channel_tools._directory import HistoryQuery

    user = "@" + "u" * 242 + ":example.org"
    assert len(user.encode()) == 255
    assert HistoryQuery(author_id=user).author_id == user
