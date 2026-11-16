"""A bot's reaction emoji and Mattermost's `/agent` token, as settings (#2084)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.core.vault import VaultScope, seal
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotRead, ChannelBotUpdate
from app.services.channel_bot import ChannelBotService, unseal_command_token

pytestmark = pytest.mark.anyio

SERVER = "https://mattermost.acme.internal"


def _create(platform: str = "mattermost", **overrides: object) -> ChannelBotCreate:
    fields: dict[str, object] = {"platform": platform, "name": "bot", "token": "t" * 20}
    if platform in {"mattermost", "imessage"}:
        fields["api_base_url"] = SERVER
    if platform == "teams":
        fields["teams_app_id"] = str(uuid.uuid4())
        fields["teams_tenant_id"] = str(uuid.uuid4())
    return ChannelBotCreate(**{**fields, **overrides})


def _row(platform: str = "mattermost") -> ChannelBot:
    organization_id = uuid.uuid4()
    return ChannelBot(
        id=uuid.uuid4(),
        organization_id=organization_id,
        platform=platform,
        name="bot",
        token_encrypted=seal(
            "t" * 20, scope=VaultScope.organization(organization_id), key_version=1
        ).ciphertext,
        created_at=datetime.now(UTC),
        secret_key_version=1,
        api_base_url=SERVER if platform == "mattermost" else None,
        access_policy={},
        is_active=True,
        webhook_mode=False,
        stream_answers=True,
        step_display="timeline",
        rate_answers=True,
        transcribe_voice_notes=True,
    )


async def _created(data: ChannelBotCreate) -> dict:
    with patch(
        "app.services.channel_bot.channel_bot_repo.create",
        new=AsyncMock(return_value=MagicMock()),
    ) as repo_create:
        await ChannelBotService(MagicMock(), organization_id=uuid.uuid4()).create(data)
    return repo_create.call_args.kwargs


async def _updated(bot: ChannelBot, **fields: object) -> dict:
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            new=AsyncMock(return_value=bot),
        ),
        patch(
            "app.services.channel_bot.channel_bot_repo.update",
            new=AsyncMock(return_value=bot),
        ) as repo_update,
    ):
        service = ChannelBotService(MagicMock(), organization_id=bot.organization_id)
        await service.update(bot.id, ChannelBotUpdate(**fields), MagicMock())
    return repo_update.call_args.kwargs["update_data"]


class TestTheReaction:
    @pytest.mark.parametrize(
        ("platform", "reaction"),
        [
            ("mattermost", "eyes"),
            ("slack", "eyes"),
            ("telegram", "eyes"),
            ("imessage", "emphasize"),
            ("discord", None),
            ("teams", None),
            ("email", None),
        ],
    )
    def test_new_bot_defaults_are_native_and_ratings_are_opt_in(
        self, platform: str, reaction: str | None
    ) -> None:
        data = _create(platform)
        assert data.ack_reaction == reaction
        assert data.rate_answers is False

    async def test_explicit_choices_survive_creation_and_unrelated_updates(self) -> None:
        created = await _created(_create(ack_reaction=None, rate_answers=True))
        assert created["ack_reaction"] is None
        assert created["rate_answers"] is True
        changed = await _updated(_row(), name="Renamed")
        assert "ack_reaction" not in changed
        assert "rate_answers" not in changed

    async def test_it_is_stored_by_its_name(self) -> None:
        assert (await _created(_create(ack_reaction="eyes")))["ack_reaction"] == "eyes"
        assert (await _updated(_row(), ack_reaction="white_check_mark"))[
            "ack_reaction"
        ] == "white_check_mark"

    @pytest.mark.parametrize("name", [":eyes:", "Eyes", "👀", ""])
    def test_anything_but_an_emoji_name_is_refused(self, name: str) -> None:
        with pytest.raises(ValidationError):
            ChannelBotUpdate(ack_reaction=name)


class TestTheMattermostCommandToken:
    async def test_it_is_sealed_and_never_read_back(self) -> None:
        stored = (await _created(_create(command_token="cmd-token-123")))["command_token_encrypted"]
        assert stored is not None and "cmd-token-123" not in stored

        updated = await _updated(_row(), command_token="cmd-token-456")
        assert "command_token" not in updated
        assert "cmd-token-456" not in updated["command_token_encrypted"]

    async def test_only_a_mattermost_bot_has_one(self) -> None:
        with pytest.raises(BadRequestError):
            await _created(_create("slack", command_token="cmd-token-123"))
        with pytest.raises(BadRequestError):
            await _updated(_row("slack"), command_token="cmd-token-123")

    def test_it_unseals_for_the_route_and_is_absent_until_set(self) -> None:
        bot = _row()
        assert unseal_command_token(bot) is None
        bot.command_token_encrypted = seal(
            "cmd-token-123", scope=VaultScope.organization(bot.organization_id), key_version=1
        ).ciphertext
        assert unseal_command_token(bot) == "cmd-token-123"
        assert bot.has_command_token

    def test_a_mattermost_bot_says_where_its_command_posts(self) -> None:
        mattermost = ChannelBotRead.model_validate(_row())
        slack = ChannelBotRead.model_validate(_row("slack"))

        assert mattermost.command_url is not None
        assert mattermost.command_url.endswith(f"/api/v1/mattermost/{mattermost.id}/commands")
        assert slack.command_url is None
