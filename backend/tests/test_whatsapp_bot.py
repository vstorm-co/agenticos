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

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError, NotFoundError
from app.core.vault import VaultScope, unseal
from app.db.models.channel_bot import ChannelBot
from app.schemas.agent_run import AgentRunRead
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotRead, ChannelBotUpdate
from app.services.channel_bot import (
    ChannelBotService,
    seal_bot_token,
    unseal_bot_token,
    unseal_webhook_secret,
    unseal_whatsapp_verify_token,
)
from app.services.channels.whatsapp_graph import (
    WhatsAppCredentials,
    WhatsAppGraph,
    WhatsAppGraphError,
    WhatsAppTokenRefused,
)
from app.services.channels.whatsapp_templates import LateTemplate, to_stored
from tests.test_run_history_schema import _row as _run_row

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


TEMPLATE = LateTemplate(
    name="late_answer", language="en_US", body="Hello, your answer is ready: {{1}} - thanks"
)


def _listing_entry(name: str, body: str, **overrides: object) -> dict:
    return {
        "name": name,
        "language": "en_US",
        "status": "APPROVED",
        "category": "UTILITY",
        "components": [{"type": "BODY", "text": body}],
        **overrides,
    }


LISTING = [
    _listing_entry("late_answer", TEMPLATE.body),
    _listing_entry("marketing", TEMPLATE.body, category="MARKETING"),
    _listing_entry("two_variables", "{{1}} and {{2}}"),
]


def _sealed_row(platform: str = "whatsapp") -> ChannelBot:
    bot = _row(platform)
    bot.token_encrypted = seal_bot_token(
        ACCESS_TOKEN, organization_id=bot.organization_id
    ).ciphertext
    bot.whatsapp_phone_number_id = PHONE_NUMBER_ID
    bot.whatsapp_account_id = ACCOUNT_ID
    return bot


async def _templates(bot: ChannelBot, listing: object) -> tuple[list[LateTemplate], MagicMock]:
    """What `whatsapp_templates` returns for a bot, with Meta's listing patched."""
    graph = MagicMock()
    graph.aclose = AsyncMock()
    if isinstance(listing, Exception):
        graph.message_templates = AsyncMock(side_effect=listing)
    else:
        graph.message_templates = AsyncMock(return_value=listing)
    with (
        patch("app.services.channel_bot.channel_bot_repo.get_for_org", AsyncMock(return_value=bot)),
        patch("app.services.channel_bot.WhatsAppGraph", return_value=graph),
    ):
        service = ChannelBotService(MagicMock(), organization_id=bot.organization_id)
        try:
            return await service.whatsapp_templates(bot.id), graph
        finally:
            # The client is closed whenever it was used, including when Meta refused.
            assert graph.aclose.await_count == graph.message_templates.await_count


async def _chosen(
    bot: ChannelBot, choice: object, listing: object = None
) -> tuple[dict, MagicMock]:
    graph = MagicMock()
    graph.aclose = AsyncMock()
    graph.message_templates = AsyncMock(return_value=LISTING if listing is None else listing)
    with (
        patch("app.services.channel_bot.WhatsAppGraph", return_value=graph),
    ):
        data = await _updated(bot, whatsapp_late_template=choice)
    return data, graph


class TestTheLateAnswerTemplate:
    async def test_the_template_list_holds_only_usable_templates(self):
        templates, graph = await _templates(_sealed_row(), LISTING)

        assert templates == [TEMPLATE]
        creds = graph.message_templates.await_args.args[0]
        assert creds.phone_number_id == PHONE_NUMBER_ID
        assert graph.message_templates.await_args.kwargs == {"account_id": ACCOUNT_ID}

    @pytest.mark.security
    @pytest.mark.parametrize(
        "failure, code",
        [(WhatsAppTokenRefused(code=190), 190), (WhatsAppGraphError(code=100), 100)],
    )
    async def test_meta_refusing_the_listing_is_a_503_that_names_no_token(self, failure, code):
        with pytest.raises(ExternalServiceError) as refused:
            await _templates(_sealed_row(), failure)

        assert refused.value.status_code == 503
        assert refused.value.details == {"code": code}
        assert ACCESS_TOKEN not in f"{refused.value.message}{refused.value.details}"

    async def test_only_a_whatsapp_bot_lists_templates(self):
        with pytest.raises(BadRequestError) as refused:
            await _templates(_sealed_row("telegram"), LISTING)

        assert refused.value.details["fields"][0]["field"] == "bot_id"

    async def test_a_whatsapp_bot_without_an_account_lists_nothing(self):
        bot = _sealed_row()
        bot.whatsapp_account_id = None

        with pytest.raises(BadRequestError):
            await _templates(bot, LISTING)

    async def test_choosing_a_template_stores_what_meta_lists(self):
        data, _ = await _chosen(_sealed_row(), {"name": "late_answer", "language": "en_US"})

        assert data["whatsapp_late_template"] == to_stored(TEMPLATE)

    async def test_a_template_meta_does_not_list_as_usable_is_refused(self):
        for choice in (
            {"name": "marketing", "language": "en_US"},
            {"name": "late_answer", "language": "pl"},
            {"name": "unknown", "language": "en_US"},
        ):
            with pytest.raises(BadRequestError) as refused:
                await _chosen(_sealed_row(), choice)

            assert refused.value.details["fields"][0]["field"] == "whatsapp_late_template"

    async def test_a_null_clears_the_template_without_asking_meta(self):
        data, graph = await _chosen(_sealed_row(), None)

        assert data == {"whatsapp_late_template": None}
        graph.message_templates.assert_not_awaited()

    async def test_an_update_without_the_template_leaves_it_alone(self):
        graph = MagicMock()
        graph.message_templates = AsyncMock()
        with patch("app.services.channel_bot.WhatsAppGraph", return_value=graph):
            data = await _updated(_sealed_row(), name="Renamed")

        assert data == {"name": "Renamed"}
        graph.message_templates.assert_not_awaited()

    @pytest.mark.parametrize("choice", [None, {"name": "late_answer", "language": "en_US"}])
    async def test_another_platform_may_not_carry_a_template(self, choice):
        with pytest.raises(BadRequestError) as refused:
            await _updated(_row("telegram"), whatsapp_late_template=choice)

        assert refused.value.details["fields"][0]["field"] == "whatsapp_late_template"

    @pytest.mark.parametrize(
        "stored, expected",
        [
            (to_stored(TEMPLATE), to_stored(TEMPLATE)),
            (None, None),
            ({"name": "late_answer", "language": "en_US", "body": "no variable"}, None),
            ("garbage", None),
        ],
    )
    async def test_a_whatsapp_bot_reads_back_its_template_and_none_when_unset_or_malformed(
        self, stored, expected
    ):
        bot = _row()
        bot.whatsapp_late_template = stored

        read = ChannelBotRead.model_validate(bot, from_attributes=True)

        assert (
            read.whatsapp_late_template and read.whatsapp_late_template.model_dump()
        ) == expected

    async def test_a_run_reads_back_why_its_answer_was_not_delivered(self):
        run = _run_row(undelivered_reason="window_no_template")

        assert AgentRunRead.model_validate(run).undelivered_reason == "window_no_template"
        assert AgentRunRead.model_validate(_run_row()).undelivered_reason is None


class TestTheTemplateIsCheckedBeforeTheRowIsLocked:
    async def test_meta_is_asked_before_the_bot_row_is_locked(self):
        bot = _sealed_row()
        calls: list[str] = []

        async def get_for_org(
            *_args: object, for_update: bool = False, **_kw: object
        ) -> ChannelBot:
            calls.append("locked read" if for_update else "read")
            return bot

        async def listing(*_args: object, **_kw: object) -> list[dict]:
            calls.append("meta")
            return LISTING

        graph = MagicMock()
        graph.aclose = AsyncMock()
        graph.message_templates = listing
        with (
            patch("app.services.channel_bot.channel_bot_repo.get_for_org", get_for_org),
            patch("app.services.channel_bot.channel_bot_repo.update", AsyncMock(return_value=bot)),
            patch("app.services.channel_bot.WhatsAppGraph", return_value=graph),
            patch(
                "app.services.channel_bot.spawn_after_commit",
                side_effect=lambda _db, coro, **_: coro.close(),
            ),
        ):
            service = ChannelBotService(MagicMock(), organization_id=bot.organization_id)
            await service.update(
                bot.id,
                ChannelBotUpdate(
                    whatsapp_late_template={"name": "late_answer", "language": "en_US"}
                ),
            )

        assert calls == ["read", "meta", "locked read"]

    async def test_the_choice_is_checked_against_the_credentials_the_same_save_sets(self):
        bot = _sealed_row()
        graph = MagicMock()
        graph.aclose = AsyncMock()
        graph.message_templates = AsyncMock(return_value=LISTING)
        with patch("app.services.channel_bot.WhatsAppGraph", return_value=graph):
            await _updated(
                bot,
                whatsapp_late_template={"name": "late_answer", "language": "en_US"},
                token="EAAG-a-new-access-token",
                whatsapp_account_id="999111",
                whatsapp_phone_number_id="555222",
            )

        creds = graph.message_templates.await_args.args[0]
        assert creds.access_token == "EAAG-a-new-access-token"
        assert creds.phone_number_id == "555222"
        assert graph.message_templates.await_args.kwargs == {"account_id": "999111"}

    async def test_a_foreign_bot_lists_no_templates(self):
        graph = MagicMock()
        with (
            patch(
                "app.services.channel_bot.channel_bot_repo.get_for_org",
                AsyncMock(return_value=None),
            ),
            patch("app.services.channel_bot.WhatsAppGraph", return_value=graph),
            pytest.raises(NotFoundError),
        ):
            await ChannelBotService(MagicMock(), organization_id=uuid.uuid4()).whatsapp_templates(
                uuid.uuid4()
            )

        graph.assert_not_called()

    @pytest.mark.security
    @pytest.mark.parametrize("status, code", [(401, 190), (400, 100)])
    async def test_nothing_meta_says_reaches_the_refusal(self, status, code):
        """Meta's own error text carries the token and a phone number: none of it may escape."""

        def answer(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status,
                json={
                    "error": {
                        "code": code,
                        "message": f"Invalid token {ACCESS_TOKEN} for +48123456789",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
        bot = _sealed_row()
        with (
            patch(
                "app.services.channel_bot.channel_bot_repo.get_for_org", AsyncMock(return_value=bot)
            ),
            patch("app.services.channel_bot.WhatsAppGraph", return_value=WhatsAppGraph(client)),
            pytest.raises(ExternalServiceError) as refused,
        ):
            await ChannelBotService(
                MagicMock(), organization_id=bot.organization_id
            ).whatsapp_templates(bot.id)
        await client.aclose()

        text = f"{refused.value.message}{refused.value.details}{refused.value.__cause__}"
        assert refused.value.details == {"code": code}
        assert ACCESS_TOKEN not in text
        assert "+48123456789" not in text
