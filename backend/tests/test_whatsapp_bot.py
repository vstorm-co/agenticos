"""A WhatsApp bot: its Cloud API registration, its sealed secrets and what it reads back (#2076).

For WhatsApp the bot's `token` is the System User access token and `webhook_secret`
is the Meta **app secret** every webhook is signed with. The business phone number
and its account are identifiers; the verify token answers Meta's subscription
handshake and is sealed apart from the app secret.
"""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.vault import VaultScope, unseal
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotRead, ChannelBotUpdate
from app.services.channel_bot import (
    ChannelBotService,
    seal_bot_token,
    unseal_bot_token,
    unseal_webhook_secret,
    unseal_whatsapp_verify_token,
)
from app.services.channels.whatsapp_graph import WhatsAppCredentials

pytestmark = pytest.mark.anyio

ACCESS_TOKEN = "EAAG-access-token-0123456789"
APP_SECRET = "app-secret-abcdef"
VERIFY_TOKEN = "verify-token-xyz"
PHONE_NUMBER_ID = "104567890123456"
ACCOUNT_ID = "207654321098765"


def _whatsapp(**overrides) -> dict:
    return {
        "platform": "whatsapp",
        "name": "Front desk",
        "token": ACCESS_TOKEN,
        "webhook_secret": APP_SECRET,
        "whatsapp_phone_number_id": PHONE_NUMBER_ID,
        "whatsapp_account_id": ACCOUNT_ID,
        "whatsapp_verify_token": VERIFY_TOKEN,
        **overrides,
    }


def _row(platform: str = "whatsapp") -> ChannelBot:
    return ChannelBot(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        platform=platform,
        name="bot",
        token_encrypted="",
        secret_key_version=1,
        webhook_mode=True,
        is_active=True,
        access_policy={},
        transcribe_voice_notes=True,
        stream_answers=True,
        step_display="timeline",
        rate_answers=True,
        created_at=datetime.now(UTC),
    )


async def _created(data: ChannelBotCreate, org: uuid.UUID | None = None) -> dict:
    """The keyword arguments `create` hands the repository."""
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.create",
            new=AsyncMock(return_value=MagicMock()),
        ) as repo_create,
        patch(
            "app.services.channel_bot.spawn_after_commit",
            side_effect=lambda _db, coro, **_: coro.close(),
        ),
    ):
        await ChannelBotService(MagicMock(), organization_id=org or uuid.uuid4()).create(data)
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
        patch(
            "app.services.channel_bot.spawn_after_commit",
            side_effect=lambda _db, coro, **_: coro.close(),
        ),
    ):
        service = ChannelBotService(MagicMock(), organization_id=bot.organization_id)
        await service.update(bot.id, ChannelBotUpdate(**fields))
    return repo_update.call_args.kwargs["update_data"]


class TestRegistering:
    @pytest.mark.parametrize(
        "missing",
        [
            "webhook_secret",
            "whatsapp_phone_number_id",
            "whatsapp_account_id",
            "whatsapp_verify_token",
        ],
    )
    @pytest.mark.security
    async def test_a_whatsapp_bot_needs_its_number_account_app_secret_and_verify_token(
        self, missing
    ):
        fields = _whatsapp()
        del fields[missing]

        with pytest.raises(ValidationError, match="A WhatsApp bot needs its phone number ID"):
            ChannelBotCreate(**fields)

        assert ChannelBotCreate(**_whatsapp()).platform == "whatsapp"

    @pytest.mark.parametrize(
        "field, value",
        [
            ("whatsapp_phone_number_id", PHONE_NUMBER_ID),
            ("whatsapp_account_id", ACCOUNT_ID),
            ("whatsapp_verify_token", VERIFY_TOKEN),
        ],
    )
    async def test_whatsapp_fields_are_refused_on_other_platforms(self, field, value):
        with pytest.raises(ValidationError, match="WhatsApp bot, not a telegram bot"):
            ChannelBotCreate(platform="telegram", name="bot", token="t" * 20, **{field: value})

    @pytest.mark.parametrize("bad", ["1234", "12ab5678", "1" * 33])
    async def test_the_number_and_account_ids_are_digits(self, bad):
        with pytest.raises(ValidationError, match="whatsapp_phone_number_id"):
            ChannelBotCreate(**_whatsapp(whatsapp_phone_number_id=bad))
        with pytest.raises(ValidationError, match="whatsapp_account_id"):
            ChannelBotCreate(**_whatsapp(whatsapp_account_id=bad))

    async def test_a_whatsapp_bot_is_always_a_webhook_bot(self):
        assert ChannelBotCreate(**_whatsapp(webhook_mode=False)).webhook_mode is True
        assert ChannelBotCreate(**_whatsapp()).webhook_mode is True

    @pytest.mark.security
    async def test_the_create_hands_the_repository_sealed_secrets_and_plain_identifiers(self):
        org = uuid.uuid4()

        kwargs = await _created(ChannelBotCreate(**_whatsapp()), org)

        scope = VaultScope.organization(org)
        version = kwargs["secret_key_version"]
        assert kwargs["whatsapp_phone_number_id"] == PHONE_NUMBER_ID
        assert kwargs["whatsapp_account_id"] == ACCOUNT_ID
        assert kwargs["webhook_mode"] is True
        assert unseal(kwargs["token_encrypted"], scope=scope, key_version=version) == ACCESS_TOKEN
        assert (
            unseal(kwargs["webhook_secret_encrypted"], scope=scope, key_version=version)
            == APP_SECRET
        )
        assert (
            unseal(kwargs["whatsapp_verify_token_encrypted"], scope=scope, key_version=version)
            == VERIFY_TOKEN
        )
        for plain in (ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN):
            assert plain not in json.dumps(
                [kwargs["token_encrypted"], kwargs["whatsapp_verify_token_encrypted"]]
            )


class TestReadingBack:
    @pytest.mark.security
    async def test_a_whatsapp_bot_reads_back_ids_but_no_secret(self):
        org = uuid.uuid4()
        sealed = seal_bot_token(ACCESS_TOKEN, organization_id=org)
        verify = seal_bot_token(VERIFY_TOKEN, organization_id=org)
        secret = seal_bot_token(APP_SECRET, organization_id=org)
        bot = _row()
        bot.organization_id = org
        bot.token_encrypted = sealed.ciphertext
        bot.webhook_secret_encrypted = secret.ciphertext
        bot.whatsapp_verify_token_encrypted = verify.ciphertext
        bot.whatsapp_phone_number_id = PHONE_NUMBER_ID
        bot.whatsapp_account_id = ACCOUNT_ID

        body = ChannelBotRead.model_validate(bot, from_attributes=True).model_dump_json()

        read = json.loads(body)
        assert read["whatsapp_phone_number_id"] == PHONE_NUMBER_ID
        assert read["whatsapp_account_id"] == ACCOUNT_ID
        assert read["has_whatsapp_verify_token"] is True
        assert read["has_webhook_secret"] is True
        for hidden in (ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN):
            assert hidden not in body
        for ciphertext in (sealed.ciphertext, verify.ciphertext, secret.ciphertext):
            assert ciphertext not in body

    async def test_a_bot_without_a_verify_token_says_so(self):
        bot = _row("telegram")

        read = ChannelBotRead.model_validate(bot, from_attributes=True)

        assert read.has_whatsapp_verify_token is False
        assert read.whatsapp_phone_number_id is None


class TestUnsealing:
    async def test_unseal_composes_the_credentials_envelope(self):
        org = uuid.uuid4()
        bot = _row()
        bot.organization_id = org
        bot.token_encrypted = seal_bot_token(ACCESS_TOKEN, organization_id=org).ciphertext
        bot.whatsapp_phone_number_id = PHONE_NUMBER_ID

        creds = WhatsAppCredentials.decode(unseal_bot_token(bot))

        assert creds == WhatsAppCredentials(
            bot_id=str(bot.id), access_token=ACCESS_TOKEN, phone_number_id=PHONE_NUMBER_ID
        )

    @pytest.mark.security
    async def test_the_verify_token_is_sealed_and_unsealed_separately_from_the_app_secret(self):
        org = uuid.uuid4()
        bot = _row()
        bot.organization_id = org
        bot.webhook_secret_encrypted = seal_bot_token(APP_SECRET, organization_id=org).ciphertext
        assert unseal_whatsapp_verify_token(bot) is None
        assert bot.has_whatsapp_verify_token is False

        bot.whatsapp_verify_token_encrypted = seal_bot_token(
            VERIFY_TOKEN, organization_id=org
        ).ciphertext

        assert unseal_whatsapp_verify_token(bot) == VERIFY_TOKEN
        assert unseal_webhook_secret(bot) == APP_SECRET
        assert bot.has_whatsapp_verify_token is True

    async def test_credentials_round_trip_and_reject_garbage(self):
        creds = WhatsAppCredentials(bot_id="b", access_token="t", phone_number_id="1")

        assert WhatsAppCredentials.decode(creds.encode()) == creds
        for garbage in ("not json", "[]", '{"bot_id": "b"}', "null"):
            with pytest.raises(ValueError, match="credentials are not readable"):
                WhatsAppCredentials.decode(garbage)


class TestUpdating:
    async def test_an_update_seals_a_new_verify_token_at_the_rows_key_version(self, monkeypatch):
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: "k1" * 20, 2: "k2" * 20})
        # The row stays at version 1 while the current key is 2: sealing at the
        # current version instead of the row's would be unreadable at the row's.
        bot = _row()
        assert bot.secret_key_version == 1

        data = await _updated(bot, whatsapp_verify_token="another-verify-token")

        assert "whatsapp_verify_token" not in data
        assert (
            unseal(
                data["whatsapp_verify_token_encrypted"],
                scope=VaultScope.organization(bot.organization_id),
                key_version=bot.secret_key_version,
            )
            == "another-verify-token"
        )

    async def test_an_update_may_change_the_number_and_account(self):
        data = await _updated(
            _row(), whatsapp_phone_number_id="999999", whatsapp_account_id="888888"
        )

        assert data == {"whatsapp_phone_number_id": "999999", "whatsapp_account_id": "888888"}

    @pytest.mark.parametrize(
        "field",
        [
            "whatsapp_phone_number_id",
            "whatsapp_account_id",
            "whatsapp_verify_token",
            "webhook_secret",
            "webhook_mode",
        ],
    )
    @pytest.mark.security
    async def test_an_update_cannot_null_a_whatsapp_bots_number_or_secrets_or_turn_off_webhooks(
        self, field
    ):
        value = False if field == "webhook_mode" else None

        with pytest.raises(BadRequestError) as refused:
            await _updated(_row(), **{field: value})

        assert refused.value.details["fields"][0]["field"] == field

    @pytest.mark.parametrize(
        "fields",
        [
            {"whatsapp_phone_number_id": "123456"},
            {"whatsapp_account_id": "123456"},
            {"whatsapp_verify_token": "some-verify-token"},
        ],
    )
    async def test_whatsapp_fields_on_another_platforms_update_are_refused(self, fields):
        (field,) = fields

        with pytest.raises(BadRequestError) as refused:
            await _updated(_row("telegram"), **fields)

        assert refused.value.details["fields"][0]["field"] == field

    async def test_other_platforms_may_still_send_webhook_mode_false(self):
        data = await _updated(_row("telegram"), webhook_mode=False)

        assert data == {"webhook_mode": False}


class TestSendHealthInTheConsoleList:
    async def _listed(self, bots: list[ChannelBot], **states: object) -> list[ChannelBotRead]:
        async def read(bot_id: uuid.UUID) -> object:
            return states.get(str(bot_id))

        with (
            patch(
                "app.services.channel_bot.channel_bot_repo.list_for_org",
                new=AsyncMock(return_value=bots),
            ),
            patch(
                "app.services.channel_bot.channel_bot_repo.count",
                new=AsyncMock(return_value=len(bots)),
            ),
            patch(
                "app.services.channel_bot.agent_exposure_repo.active_agents_for_bots",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.channel_bot.connection_state.read", new=AsyncMock(side_effect=read)
            ),
        ):
            rows, _ = await ChannelBotService(MagicMock(), organization_id=uuid.uuid4()).list_all()
        return rows

    async def test_the_console_list_shows_a_whatsapp_bots_send_health(self):
        from app.services.channels.connection_state import ChannelConnection
        from app.services.channels.whatsapp_graph import TOKEN_REFUSED

        whatsapp, telegram = _row(), _row("telegram")
        down = ChannelConnection(state="down", reason=TOKEN_REFUSED)

        rows = await self._listed(
            [whatsapp, telegram], **{str(whatsapp.id): down, str(telegram.id): down}
        )

        by_id = {row.id: row for row in rows}
        assert by_id[whatsapp.id].connection is not None
        assert by_id[whatsapp.id].connection.state == "down"
        assert by_id[whatsapp.id].connection.reason == TOKEN_REFUSED
        # A Telegram webhook bot holds no socket: a "down" beside it would be a design, not a fault.
        assert by_id[telegram.id].connection is None


def test_a_whatsapp_bot_reads_back_its_callback_url_and_no_other_does():
    def read(platform: str) -> ChannelBotRead:
        return ChannelBotRead(
            id=uuid.uuid4(),
            platform=platform,
            name="bot",
            is_active=True,
            webhook_mode=True,
            webhook_url=None,
            access_policy={"mode": "open"},
            created_at="2026-11-02T00:00:00Z",
        )

    whatsapp = read("whatsapp")
    assert whatsapp.whatsapp_callback_url is not None
    assert whatsapp.whatsapp_callback_url.endswith(f"/api/v1/whatsapp/{whatsapp.id}/webhook")
    assert read("slack").whatsapp_callback_url is None
