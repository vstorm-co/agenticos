"""The shared secret that authenticates an inbound webhook, sealed (#22).

Telegram sends it back in `X-Telegram-Bot-Api-Secret-Token`; a Mattermost
outgoing webhook carries it in the body, where it is the whole of the
authentication because Mattermost does not sign payloads. So it is the only thing
standing between the internet and a run charged to an organization, and it sat in
a plaintext column beside three sealed ones.

`grep -rn webhook_secret tests/` returned nothing before this file: no test
proved the sealing, and none proved the refusals it protects.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.exceptions import BadRequestError
from app.core.vault import VaultScope, seal, unseal
from app.db.models.channel_bot import ChannelBot
from app.main import app
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotUpdate
from app.services.channel_bot import ChannelBotService, unseal_webhook_secret
from app.services.channels import register_adapter
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.telegram import TelegramAdapter

pytestmark = pytest.mark.anyio


def _bot_service(bot: ChannelBot | None) -> MagicMock:
    """A `ChannelBotService` that answers the inbound lookup with `bot`."""
    service = MagicMock()
    service.find_active = AsyncMock(return_value=bot)
    return service


def _sealed_bot(secret: str | None, *, organization_id: uuid.UUID | None = None) -> ChannelBot:
    """A bot row carrying `secret`, sealed for its own organization."""
    org_id = organization_id or uuid.uuid4()
    bot = ChannelBot(
        id=uuid.uuid4(),
        organization_id=org_id,
        platform="mattermost",
        name="bot",
        token_encrypted="",
        secret_key_version=1,
    )
    bot.webhook_secret_encrypted = (
        None if secret is None else seal(secret, scope=VaultScope.organization(org_id)).ciphertext
    )
    return bot


class TestSealing:
    async def test_a_minted_secret_is_sealed_before_it_reaches_the_repository(self):
        """The value handed to the row is an envelope, never the secret itself."""
        org_id = uuid.uuid4()
        with patch(
            "app.services.channel_bot.channel_bot_repo.create",
            new=AsyncMock(return_value=MagicMock()),
        ) as repo_create:
            service = ChannelBotService(MagicMock(), organization_id=org_id)
            await service.create(
                ChannelBotCreate(platform="telegram", name="bot", token="t" * 20, webhook_mode=True)
            )

        stored = repo_create.call_args.kwargs["webhook_secret_encrypted"]
        assert stored is not None
        recovered = unseal(stored, scope=VaultScope.organization(org_id))
        assert recovered
        assert recovered not in stored

    async def test_a_polling_bot_gets_no_secret_at_all(self):
        """No webhook, nothing to authenticate - an envelope around nothing is
        worse than a null, because it reads as configured."""
        with patch(
            "app.services.channel_bot.channel_bot_repo.create",
            new=AsyncMock(return_value=MagicMock()),
        ) as repo_create:
            service = ChannelBotService(MagicMock(), organization_id=uuid.uuid4())
            await service.create(
                ChannelBotCreate(
                    platform="telegram", name="bot", token="t" * 20, webhook_mode=False
                )
            )

        assert repo_create.call_args.kwargs["webhook_secret_encrypted"] is None

    async def test_the_secret_is_sealed_at_the_rows_key_version(self):
        """One `secret_key_version` covers every envelope in the row, so a
        staged rotation can tell which rows it has already moved."""
        org_id = uuid.uuid4()
        with patch(
            "app.services.channel_bot.channel_bot_repo.create",
            new=AsyncMock(return_value=MagicMock()),
        ) as repo_create:
            service = ChannelBotService(MagicMock(), organization_id=org_id)
            await service.create(
                ChannelBotCreate(platform="telegram", name="bot", token="t" * 20, webhook_mode=True)
            )

        kwargs = repo_create.call_args.kwargs
        assert unseal(
            kwargs["webhook_secret_encrypted"],
            scope=VaultScope.organization(org_id),
            key_version=kwargs["secret_key_version"],
        )


class TestUnsealing:
    async def test_the_secret_survives_the_round_trip(self):
        bot = _sealed_bot("s3cret-token")
        assert unseal_webhook_secret(bot) == "s3cret-token"

    async def test_an_unset_secret_is_none_rather_than_an_error(self):
        """The callers name it themselves: a webhook that cannot be
        authenticated is refused, and the refusal says which bot to configure."""
        assert unseal_webhook_secret(_sealed_bot(None)) is None

    async def test_a_ciphertext_from_another_organization_fails_to_unwrap(self):
        """The tenant boundary is in the key derivation, not in a WHERE clause -
        a row copied between organizations must not decrypt."""
        bot = _sealed_bot("s3cret-token")
        bot.organization_id = uuid.uuid4()
        with pytest.raises(BadRequestError):
            unseal_webhook_secret(bot)


class TestEnteringWebhookMode:
    """A bot switched to webhook mode after creation had no secret at all (#4).

    One was minted at create time and only when `webhook_mode` was already true,
    which is not the schema's default - so the common path produced a bot whose
    receiver had nothing to verify against.
    """

    async def _update(self, bot: ChannelBot, **fields: object) -> dict:
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
            await service.update(bot.id, ChannelBotUpdate(**fields))
        return repo_update.call_args.kwargs["update_data"]

    async def test_switching_a_bot_to_webhook_mode_mints_a_secret(self):
        bot = _sealed_bot(None)
        update_data = await self._update(bot, webhook_mode=True)
        assert unseal(
            update_data["webhook_secret_encrypted"],
            scope=VaultScope.organization(bot.organization_id),
        )

    async def test_a_bot_already_in_webhook_mode_keeps_the_secret_it_has(self):
        """Minting a second one would silently invalidate the secret the
        platform was handed when the webhook was registered."""
        bot = _sealed_bot("already-registered")
        update_data = await self._update(bot, webhook_mode=True, name="renamed")
        assert "webhook_secret_encrypted" not in update_data

    async def test_an_unrelated_update_mints_nothing(self):
        bot = _sealed_bot(None)
        update_data = await self._update(bot, name="renamed")
        assert "webhook_secret_encrypted" not in update_data

    async def test_leaving_webhook_mode_mints_nothing(self):
        bot = _sealed_bot(None)
        update_data = await self._update(bot, webhook_mode=False)
        assert "webhook_secret_encrypted" not in update_data


class TestTheRowSaysWhetherItIsConfigured:
    def test_a_sealed_secret_reads_as_configured(self):
        assert _sealed_bot("s3cret-token").has_webhook_secret is True

    def test_no_secret_reads_as_unconfigured(self):
        assert _sealed_bot(None).has_webhook_secret is False


@pytest.fixture
def registered_adapters():
    """The two adapters the receivers look up.

    Registered by the lifespan in production, and the test client does not run
    one - without this the routes raise `KeyError` before reaching the refusal
    under test, which reads like a passing 500.
    """
    register_adapter(TelegramAdapter())
    register_adapter(MattermostAdapter())


@pytest.mark.usefixtures("registered_adapters")
class TestTheReceiversRefuse:
    """Both webhook routes, asked the same question: does an unauthenticated
    request reach `process_channel_event`?"""

    async def _post(self, client: AsyncClient, path: str, bot: ChannelBot | None, **kwargs) -> int:
        app.dependency_overrides[deps.get_channel_bot_service] = lambda: _bot_service(bot)
        try:
            response = await client.post(path, **kwargs)
        finally:
            app.dependency_overrides.pop(deps.get_channel_bot_service, None)
        return response.status_code

    async def test_a_telegram_bot_with_no_secret_is_refused(self, client: AsyncClient):
        """`if secret and not verify(...)` let this through as a genuine update,
        so any bot created in polling mode - the schema's default - answered an
        unauthenticated POST from anyone who guessed its id (#4)."""
        bot = _sealed_bot(None)
        status = await self._post(
            client, f"/api/v1/telegram/{bot.id}/webhook", bot, json={"update_id": 1}
        )
        assert status == 403

    async def test_a_telegram_bot_with_a_wrong_secret_is_refused(self, client: AsyncClient):
        bot = _sealed_bot("the-real-secret")
        status = await self._post(
            client,
            f"/api/v1/telegram/{bot.id}/webhook",
            bot,
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "not-it"},
        )
        assert status == 403

    async def test_a_mattermost_bot_with_no_secret_is_refused(self, client: AsyncClient):
        bot = _sealed_bot(None)
        status = await self._post(
            client, f"/api/v1/mattermost/{bot.id}/webhook", bot, json={"text": "hello"}
        )
        assert status == 403

    async def test_an_unknown_bot_answers_200_without_running_anything(self, client: AsyncClient):
        """Not 404: an unknown or disabled bot is not something the sender can
        fix, and enough 4xx makes the platform disable the integration."""
        status = await self._post(
            client, f"/api/v1/telegram/{uuid.uuid4()}/webhook", None, json={"update_id": 1}
        )
        assert status == 200
