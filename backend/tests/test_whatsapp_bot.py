"""A WhatsApp bot: its Cloud API registration, its sealed secrets and what it reads back (#2076).

For WhatsApp the bot's `token` is the System User access token and `webhook_secret`
is the Meta **app secret** every webhook is signed with. The business phone number
and its account are identifiers; the verify token answers Meta's subscription
handshake and is sealed apart from the app secret.
"""

import contextlib
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
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


async def _created(
    data: ChannelBotCreate, org: uuid.UUID | None = None, actor_user_id: uuid.UUID | None = None
) -> dict:
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
        await ChannelBotService(MagicMock(), organization_id=org or uuid.uuid4()).create(
            data, actor_user_id=actor_user_id
        )
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
        await service.update(bot.id, ChannelBotUpdate(**fields), actor_user_id=None)
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
                actor_user_id=None,
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


_OTHER_PLATFORMS = ["telegram", "slack", "discord", "teams", "mattermost"]
_PUBLIC_LINE_KEYS = ["answer_unlinked_direct", "accept_customer_files"]
_NO_CEILING = BadRequestError(message="A bot that answers people ... needs a spending limit.")


def _other_platform(platform: str, **overrides) -> dict:
    fields: dict = {"platform": platform, "name": "bot", "token": "t" * 20, **overrides}
    if platform == "teams":
        fields.update(teams_app_id=str(uuid.uuid4()), teams_tenant_id=str(uuid.uuid4()))
    if platform == "mattermost":
        fields.update(api_base_url="https://chat.example.com")
    return fields


def _bot_with_policy(policy: dict, platform: str = "whatsapp") -> ChannelBot:
    bot = _row(platform)
    bot.access_policy = policy
    return bot


@contextlib.contextmanager
def _ceiling(*, missing: bool):
    """The refusal a line with no spending limit gets, or a ceiling that exists."""
    with (
        patch("app.services.channel_bot.bot_served_spec", new=AsyncMock(return_value=None)) as spec,
        patch(
            "app.services.channel_bot.refuse_without_ceiling",
            new=AsyncMock(side_effect=_NO_CEILING if missing else None),
        ) as refuse,
        patch("app.services.channel_bot.record_audit", new=AsyncMock()) as audit,
    ):
        yield SimpleNamespace(spec=spec, refuse=refuse, audit=audit)


async def _saved(
    bot: ChannelBot, policy: dict | None, actor_user_id: uuid.UUID | None = None, **other: object
) -> AsyncMock:
    """Update `bot` through the service and return what the repository was given."""
    fields = {} if policy is None else {"access_policy": policy}
    fields.update(other)
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            new=AsyncMock(return_value=bot),
        ),
        patch(
            "app.services.channel_bot.channel_bot_repo.update", new=AsyncMock(return_value=bot)
        ) as repo_update,
        patch(
            "app.services.channel_bot.spawn_after_commit",
            side_effect=lambda _db, coro, **_: coro.close(),
        ),
    ):
        await ChannelBotService(MagicMock(), organization_id=bot.organization_id).update(
            bot.id, ChannelBotUpdate(**fields), actor_user_id=actor_user_id
        )
    return repo_update


class TestThePublicLineIsWhatsAppOnly:
    @pytest.mark.security
    @pytest.mark.parametrize("platform", _OTHER_PLATFORMS)
    @pytest.mark.parametrize("key", _PUBLIC_LINE_KEYS)
    async def test_the_keys_are_refused_on_another_platform_at_create(self, platform, key):
        data = ChannelBotCreate(**_other_platform(platform, access_policy={key: True}))

        with _ceiling(missing=False), pytest.raises(BadRequestError) as refused:
            await _created(data)

        assert refused.value.details["fields"][0]["field"] == f"access_policy.{key}"

    @pytest.mark.security
    @pytest.mark.parametrize("platform", _OTHER_PLATFORMS)
    @pytest.mark.parametrize("key", _PUBLIC_LINE_KEYS)
    async def test_the_keys_are_refused_on_another_platform_at_update(self, platform, key):
        bot = _bot_with_policy({}, platform)

        with _ceiling(missing=False), pytest.raises(BadRequestError) as refused:
            await _saved(bot, {key: True})

        assert refused.value.details["fields"][0]["field"] == f"access_policy.{key}"

    @pytest.mark.parametrize("platform", _OTHER_PLATFORMS)
    async def test_the_keys_off_are_what_every_other_bot_carries(self, platform):
        data = ChannelBotCreate(**_other_platform(platform))

        with _ceiling(missing=False) as seen:
            kwargs = await _created(data)
            await _saved(_bot_with_policy({}, platform), {"mode": "open"})

        assert kwargs["access_policy"]["answer_unlinked_direct"] is False
        assert kwargs["access_policy"]["accept_customer_files"] is False
        seen.refuse.assert_not_awaited()
        seen.audit.assert_not_awaited()


class TestOpeningALineToStrangers:
    @pytest.mark.security
    async def test_group_only_is_refused_while_the_line_is_public_at_create(self):
        data = ChannelBotCreate(
            **_whatsapp(access_policy={"mode": "group_only", "answer_unlinked_direct": True})
        )

        with _ceiling(missing=False), pytest.raises(BadRequestError) as refused:
            await _created(data)

        assert refused.value.details["fields"][0]["field"] == "access_policy.mode"

    @pytest.mark.security
    async def test_group_only_is_refused_while_the_line_is_public_at_update(self):
        with _ceiling(missing=False), pytest.raises(BadRequestError) as refused:
            await _saved(
                _bot_with_policy({}), {"mode": "group_only", "answer_unlinked_direct": True}
            )

        assert refused.value.details["fields"][0]["field"] == "access_policy.mode"

    async def test_group_only_is_fine_while_the_line_is_not_public(self):
        with _ceiling(missing=False):
            repo = await _saved(_bot_with_policy({}), {"mode": "group_only"})

        repo.assert_awaited_once()

    @pytest.mark.security
    async def test_turning_it_on_needs_a_ceiling(self):
        bot = _bot_with_policy({})

        with _ceiling(missing=True) as seen, pytest.raises(BadRequestError):
            await _saved(bot, {"answer_unlinked_direct": True})

        seen.refuse.assert_awaited_once()
        assert seen.refuse.await_args.kwargs["channel_bot_id"] == bot.id
        assert seen.refuse.await_args.kwargs["organization_id"] == bot.organization_id
        seen.audit.assert_not_awaited()

    @pytest.mark.security
    async def test_a_refused_switch_writes_nothing(self):
        bot = _bot_with_policy({})
        update = AsyncMock()

        with (
            _ceiling(missing=True),
            patch("app.services.channel_bot.channel_bot_repo.update", new=update),
            patch(
                "app.services.channel_bot.channel_bot_repo.get_for_org",
                new=AsyncMock(return_value=bot),
            ),
            pytest.raises(BadRequestError),
        ):
            await ChannelBotService(MagicMock(), organization_id=bot.organization_id).update(
                bot.id,
                ChannelBotUpdate(access_policy={"answer_unlinked_direct": True}),
                actor_user_id=None,
            )

        update.assert_not_awaited()

    @pytest.mark.security
    async def test_opening_the_line_by_changing_the_mode_needs_a_ceiling(self):
        """The raw key is `True` before and after: it was the mode that closed the line,
        and the mode that opens it."""
        bot = _bot_with_policy({"mode": "jwt_linked", "answer_unlinked_direct": True})

        with _ceiling(missing=True) as seen, pytest.raises(BadRequestError):
            await _saved(bot, {"mode": "open", "answer_unlinked_direct": True})

        seen.refuse.assert_awaited_once()

    @pytest.mark.security
    async def test_opening_the_line_by_dropping_require_link_needs_a_ceiling(self):
        bot = _bot_with_policy(
            {"mode": "open", "require_link": True, "answer_unlinked_direct": True}
        )

        with _ceiling(missing=True) as seen, pytest.raises(BadRequestError):
            await _saved(
                bot, {"mode": "open", "require_link": False, "answer_unlinked_direct": True}
            )

        seen.refuse.assert_awaited_once()

    @pytest.mark.security
    async def test_opening_the_line_is_audited_with_the_actor(self):
        bot, actor = (
            _bot_with_policy({"mode": "jwt_linked", "answer_unlinked_direct": True}),
            uuid.uuid4(),
        )

        with _ceiling(missing=False) as seen:
            await _saved(bot, {"mode": "open", "answer_unlinked_direct": True}, actor_user_id=actor)

        seen.audit.assert_awaited_once()
        assert seen.audit.await_args.kwargs == {
            "actor_user_id": actor,
            "organization_id": bot.organization_id,
            "action": "channel.bot.public_line_changed",
            "target_type": "channel_bot",
            "target_id": str(bot.id),
            "details": {"answers_unlinked": True},
        }

    @pytest.mark.security
    async def test_closing_the_line_with_require_link_is_audited(self):
        bot = _bot_with_policy({"mode": "open", "answer_unlinked_direct": True})

        with _ceiling(missing=False) as seen:
            await _saved(
                bot,
                {"mode": "open", "require_link": True, "answer_unlinked_direct": True},
                actor_user_id=uuid.uuid4(),
            )

        seen.refuse.assert_not_awaited()
        seen.audit.assert_awaited_once()
        assert seen.audit.await_args.kwargs["details"] == {"answers_unlinked": False}

    @pytest.mark.security
    async def test_turning_it_off_needs_nothing_and_is_audited(self):
        bot = _bot_with_policy({"mode": "open", "answer_unlinked_direct": True})

        with _ceiling(missing=True) as seen:
            await _saved(bot, {"mode": "open"}, actor_user_id=uuid.uuid4())

        seen.refuse.assert_not_awaited()
        assert seen.audit.await_args.kwargs["details"] == {"answers_unlinked": False}

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("stored", "sent"),
        [
            (
                {"mode": "open", "answer_unlinked_direct": True},
                {"mode": "open", "rate_limit_rpm": 3, "answer_unlinked_direct": True},
            ),
            ({"mode": "open"}, {"mode": "whitelist", "whitelist": ["x"]}),
            ({"mode": "jwt_linked", "answer_unlinked_direct": True}, {"mode": "jwt_linked"}),
        ],
        ids=["still open", "still closed", "closed by the mode before and after"],
    )
    async def test_an_update_that_does_not_change_the_effective_state_is_not_audited(
        self, stored, sent
    ):
        with _ceiling(missing=True) as seen:
            await _saved(_bot_with_policy(stored), sent, actor_user_id=uuid.uuid4())

        seen.audit.assert_not_awaited()
        seen.refuse.assert_not_awaited()

    async def test_an_update_that_sends_no_policy_touches_neither(self):
        with _ceiling(missing=True) as seen:
            await _saved(_bot_with_policy({"mode": "open", "answer_unlinked_direct": True}), None)

        seen.audit.assert_not_awaited()
        seen.refuse.assert_not_awaited()

    @pytest.mark.security
    async def test_a_bot_created_with_the_line_open_needs_a_ceiling_and_is_audited(self):
        data = ChannelBotCreate(**_whatsapp(access_policy={"answer_unlinked_direct": True}))
        actor = uuid.uuid4()

        with _ceiling(missing=False) as seen:
            await _created(data, actor_user_id=actor)

        seen.refuse.assert_awaited_once()
        assert seen.refuse.await_args.kwargs["channel_bot_id"] is None
        assert seen.audit.await_args.kwargs["actor_user_id"] == actor
        assert seen.audit.await_args.kwargs["details"] == {"answers_unlinked": True}
        assert seen.audit.await_args.kwargs["action"] == "channel.bot.public_line_changed"

    @pytest.mark.security
    async def test_a_bot_created_with_the_line_open_and_no_ceiling_is_not_created(self):
        data = ChannelBotCreate(**_whatsapp(access_policy={"answer_unlinked_direct": True}))
        create = AsyncMock()

        with (
            _ceiling(missing=True),
            patch("app.services.channel_bot.channel_bot_repo.create", new=create),
            pytest.raises(BadRequestError),
        ):
            await ChannelBotService(MagicMock(), organization_id=uuid.uuid4()).create(
                data, actor_user_id=None
            )

        create.assert_not_awaited()

    async def test_a_bot_created_with_the_line_shut_is_neither_checked_nor_audited(self):
        with _ceiling(missing=True) as seen:
            await _created(ChannelBotCreate(**_whatsapp()))

        seen.refuse.assert_not_awaited()
        seen.audit.assert_not_awaited()


class TestReactivatingALine:
    async def _activated(self, policy: dict | str) -> tuple[AsyncMock, AsyncMock]:
        bot = _bot_with_policy(policy)
        bot.is_active = False
        update = AsyncMock(return_value=bot)
        with (
            patch(
                "app.services.channel_bot.channel_bot_repo.get_for_org",
                new=AsyncMock(return_value=bot),
            ),
            patch("app.services.channel_bot.channel_bot_repo.update", new=update),
            patch(
                "app.services.channel_bot.spawn_after_commit",
                side_effect=lambda _db, coro, **_: coro.close(),
            ),
        ):
            await ChannelBotService(MagicMock(), organization_id=bot.organization_id).activate(
                bot.id
            )
        return update, bot

    @pytest.mark.security
    async def test_a_line_that_answers_strangers_needs_a_ceiling_to_come_back(self):
        with _ceiling(missing=True) as seen, pytest.raises(BadRequestError):
            await self._activated({"mode": "open", "answer_unlinked_direct": True})

        seen.refuse.assert_awaited_once()

    @pytest.mark.security
    async def test_a_refused_reactivation_leaves_the_bot_off(self):
        update = AsyncMock()
        bot = _bot_with_policy({"mode": "open", "answer_unlinked_direct": True})
        bot.is_active = False

        with (
            _ceiling(missing=True),
            patch("app.services.channel_bot.channel_bot_repo.update", new=update),
            patch(
                "app.services.channel_bot.channel_bot_repo.get_for_org",
                new=AsyncMock(return_value=bot),
            ),
            pytest.raises(BadRequestError),
        ):
            await ChannelBotService(MagicMock(), organization_id=bot.organization_id).activate(
                bot.id
            )

        update.assert_not_awaited()
        assert bot.is_active is False

    async def test_a_line_that_answers_strangers_comes_back_with_a_ceiling(self):
        with _ceiling(missing=False) as seen:
            update, _bot = await self._activated({"mode": "open", "answer_unlinked_direct": True})

        seen.refuse.assert_awaited_once()
        update.assert_awaited_once()

    @pytest.mark.security
    @pytest.mark.parametrize(
        "policy",
        [
            {"mode": "open"},
            {"mode": "jwt_linked", "answer_unlinked_direct": True},
            {"mode": "open", "require_link": True, "answer_unlinked_direct": True},
        ],
        ids=["never public", "closed by the mode", "closed by require_link"],
    )
    async def test_a_line_that_does_not_answer_strangers_needs_nothing_to_come_back(self, policy):
        with _ceiling(missing=True) as seen:
            update, _bot = await self._activated(policy)

        seen.refuse.assert_not_awaited()
        update.assert_awaited_once()


class TestReactivatingByUpdate:
    """`is_active` is a column an update can send, so it is the same way back as `activate`."""

    @pytest.mark.security
    async def test_a_line_that_answers_strangers_needs_a_ceiling_to_come_back(self):
        bot = _bot_with_policy(_PUBLIC)
        bot.is_active = False

        with _ceiling(missing=True) as seen, pytest.raises(BadRequestError):
            await _saved(bot, None, is_active=True)

        seen.refuse.assert_awaited_once()

    @pytest.mark.security
    async def test_a_refused_one_stays_off(self):
        bot = _bot_with_policy(_PUBLIC)
        bot.is_active = False
        update = AsyncMock()

        with (
            _ceiling(missing=True),
            patch("app.services.channel_bot.channel_bot_repo.update", new=update),
            patch(
                "app.services.channel_bot.channel_bot_repo.get_for_org",
                new=AsyncMock(return_value=bot),
            ),
            pytest.raises(BadRequestError),
        ):
            await ChannelBotService(MagicMock(), organization_id=bot.organization_id).update(
                bot.id, ChannelBotUpdate(is_active=True), actor_user_id=None
            )

        update.assert_not_awaited()

    async def test_it_comes_back_with_a_ceiling(self):
        bot = _bot_with_policy(_PUBLIC)
        bot.is_active = False

        with _ceiling(missing=False) as seen:
            repo = await _saved(bot, None, is_active=True)

        seen.refuse.assert_awaited_once()
        repo.assert_awaited_once()

    @pytest.mark.security
    async def test_reactivating_and_changing_the_policy_is_asked_once(self):
        bot = _bot_with_policy({"mode": "open"})
        bot.is_active = False

        with _ceiling(missing=True) as seen, pytest.raises(BadRequestError):
            await _saved(bot, _PUBLIC, is_active=True)

        seen.refuse.assert_awaited_once()

    @pytest.mark.parametrize(
        "fields",
        [{"is_active": False}, {"name": "renamed"}],
        ids=["switching off", "an unrelated change"],
    )
    async def test_a_line_already_on_is_not_asked_again(self, fields):
        bot = _bot_with_policy(_PUBLIC)

        with _ceiling(missing=True) as seen:
            await _saved(bot, None, **fields)

        seen.refuse.assert_not_awaited()

    async def test_a_closed_line_comes_back_freely(self):
        bot = _bot_with_policy({"mode": "open"})
        bot.is_active = False

        with _ceiling(missing=True) as seen:
            await _saved(bot, None, is_active=True)

        seen.refuse.assert_not_awaited()


class TestWhatTheCeilingIsAskedAbout:
    @pytest.mark.security
    async def test_activate_asks_about_the_agent_the_bot_is_bound_to(self):
        spec = object()

        with _ceiling(missing=False) as seen:
            seen.spec.return_value = spec
            await TestReactivatingALine()._activated(_PUBLIC)

        assert seen.refuse.await_args.kwargs["spec"] is spec

    @pytest.mark.security
    async def test_update_asks_about_the_agent_the_bot_is_bound_to(self):
        spec = object()

        with _ceiling(missing=False) as seen:
            seen.spec.return_value = spec
            await _saved(_bot_with_policy({}), _PUBLIC)

        assert seen.refuse.await_args.kwargs["spec"] is spec

    @pytest.mark.security
    @pytest.mark.parametrize(
        "policy",
        [
            {"mode": "jwt_linked", "answer_unlinked_direct": True},
            {"mode": "open", "require_link": True, "answer_unlinked_direct": True},
        ],
        ids=["jwt_linked", "require_link"],
    )
    async def test_a_bot_created_with_the_key_on_but_the_line_closed_needs_no_ceiling(self, policy):
        with _ceiling(missing=True) as seen:
            kwargs = await _created(ChannelBotCreate(**_whatsapp(access_policy=policy)))

        seen.refuse.assert_not_awaited()
        seen.audit.assert_not_awaited()
        assert kwargs["access_policy"]["answer_unlinked_direct"] is True

    @pytest.mark.security
    async def test_a_policy_stored_as_json_text_is_read_not_crashed_on(self):
        text = '{"mode": "open", "answer_unlinked_direct": true}'

        with _ceiling(missing=True) as seen, pytest.raises(BadRequestError):
            await TestReactivatingALine()._activated(text)
        with _ceiling(missing=False) as seen:
            await _saved(_bot_with_policy('{"mode": "open"}'), None, actor_user_id=None)
            seen.refuse.assert_not_awaited()
            await _saved(_bot_with_policy(text), {"mode": "open"})
            assert seen.audit.await_args.kwargs["details"] == {"answers_unlinked": False}


_PUBLIC = {"mode": "open", "answer_unlinked_direct": True}
