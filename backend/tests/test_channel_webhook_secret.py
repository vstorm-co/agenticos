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

from app.core.exceptions import BadRequestError
from app.core.vault import VaultScope, seal, unseal
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import ChannelBotCreate
from app.services.channel_bot import ChannelBotService, unseal_webhook_secret

pytestmark = pytest.mark.anyio


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


class TestTheRowSaysWhetherItIsConfigured:
    def test_a_sealed_secret_reads_as_configured(self):
        assert _sealed_bot("s3cret-token").has_webhook_secret is True

    def test_no_secret_reads_as_unconfigured(self):
        assert _sealed_bot(None).has_webhook_secret is False
