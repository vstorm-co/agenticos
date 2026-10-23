"""Push to iPhones (#2097): the organization's APNs key - what is accepted, how it
is kept and audited - and a send, with every answer Apple gives."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)
from pydantic import ValidationError

from app.core.exceptions import AppException, BadRequestError, NotFoundError
from app.core.vault import VaultScope, seal, unseal
from app.schemas.push import ApnsDeviceCreate, ApnsKeyUpdate, ApnsRead
from app.services import apns
from app.services import deployment_settings as settings_module
from app.services.apns import ApnsAnswer, ApnsService, check_key, http2_transport
from app.services.deployment_settings import APNS_COLUMNS, DeploymentSettingsService
from app.services.push import PushService
from app.services.web_push import PushMessage, PushOutcome

pytestmark = pytest.mark.anyio

MODULE = "app.services.apns"
TOKEN = "a1" * 32
MESSAGE = PushMessage(title="Acme", body="Run done", url="/runs?run=r1", tag="n" * 80)


def _pem(key: ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey) -> str:
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


P8 = _pem(ec.generate_private_key(ec.SECP256R1()))


def _row(*, sandbox: bool = False, **overrides: object) -> SimpleNamespace:
    sealed = seal(P8, scope=VaultScope.deployment())
    values: dict[str, object] = {
        "apns_private_key": sealed.ciphertext,
        "apns_key_version": sealed.key_version,
        "apns_key_id": "KEY1234567",
        "apns_team_id": "TEAM123456",
        "apns_topic": "com.acme.agenticos",
        "apns_sandbox": sandbox,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _device() -> MagicMock:
    return MagicMock(id=uuid4(), token=TOKEN)


class _Apple:
    """APNs, answering each post in turn - or raising, for an answer that never came."""

    def __init__(self, *answers: ApnsAnswer | Exception):
        self.answers = list(answers)
        self.posts: list[tuple[str, dict[str, str], bytes]] = []

    async def post(self, url: str, *, headers: dict[str, str], body: bytes) -> ApnsAnswer:
        self.posts.append((url, headers, body))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[_Apple]:
        yield self


@pytest.fixture(autouse=True)
def _fresh_provider_tokens() -> None:
    apns._provider_tokens.clear()


class TestTheKey:
    def test_an_ec_p256_key_is_accepted(self) -> None:
        check_key(P8)

    @pytest.mark.parametrize(
        "pem",
        [
            "not a key",
            _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)),
            _pem(ec.generate_private_key(ec.SECP384R1())),
        ],
        # The keys are generated at collection, so their text cannot be the test ids:
        # each xdist worker would collect a different name and the run would stop.
        ids=["not-a-key", "rsa-2048", "ec-p384"],
    )
    def test_anything_else_is_refused(self, pem: str) -> None:
        with pytest.raises(BadRequestError):
            check_key(pem)

    def test_the_form_holds_apples_shapes_and_hides_the_key(self) -> None:
        data = ApnsKeyUpdate.model_validate(
            {
                "key_id": "KEY1234567",
                "team_id": "TEAM123456",
                "topic": "com.acme.agenticos",
                "private_key": P8,
            }
        )
        assert data.environment == "production"
        assert P8 not in repr(data)
        for broken in ({"key_id": "short"}, {"topic": "no-dots"}, {"environment": "staging"}):
            with pytest.raises(ValidationError):
                ApnsKeyUpdate.model_validate(
                    {
                        "key_id": "KEY1234567",
                        "team_id": "TEAM123456",
                        "topic": "com.acme.agenticos",
                        "private_key": P8,
                        **broken,
                    }
                )

    def test_a_device_token_is_hex(self) -> None:
        assert ApnsDeviceCreate(token=TOKEN).token == TOKEN
        with pytest.raises(ValidationError):
            ApnsDeviceCreate(token="Z" * 64)


class TestSettingTheKey:
    @pytest.fixture(autouse=True)
    def _quiet(self, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        monkeypatch.setattr(
            settings_module, "NotificationService", MagicMock(return_value=AsyncMock())
        )
        recorded = AsyncMock()
        monkeypatch.setattr(settings_module, "record_audit", recorded)
        return recorded

    async def test_it_is_sealed_for_the_deployment_and_audited_without_the_key(
        self, monkeypatch: pytest.MonkeyPatch, _quiet: AsyncMock
    ) -> None:
        upsert = AsyncMock()
        monkeypatch.setattr(settings_module.deployment_settings_repo, "upsert", upsert)
        stored = _row(sandbox=True)
        with patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=stored)):
            read = await DeploymentSettingsService(AsyncMock()).set_apns_key(
                actor_user_id=uuid4(),
                data=ApnsKeyUpdate.model_validate(
                    {
                        "key_id": "KEY1234567",
                        "team_id": "TEAM123456",
                        "topic": "com.acme.agenticos",
                        "environment": "sandbox",
                        "private_key": f"\n{P8}\n",
                    }
                ),
            )
        written = upsert.await_args.kwargs["update_data"]
        assert written["apns_sandbox"] is True and written["apns_topic"] == "com.acme.agenticos"
        assert unseal(written["apns_private_key"], scope=VaultScope.deployment()) == P8.strip()
        with pytest.raises(AppException):
            unseal(written["apns_private_key"], scope=VaultScope.user(uuid4()))
        assert read == ApnsRead(
            configured=True,
            key_id="KEY1234567",
            team_id="TEAM123456",
            topic="com.acme.agenticos",
            environment="sandbox",
        )
        assert _quiet.await_args.kwargs["details"] == {"fields": ["apns"]}
        assert "BEGIN" not in str(_quiet.await_args)

    async def test_a_key_that_is_not_one_is_refused_before_anything_is_written(
        self, monkeypatch: pytest.MonkeyPatch, _quiet: AsyncMock
    ) -> None:
        upsert = AsyncMock()
        monkeypatch.setattr(settings_module.deployment_settings_repo, "upsert", upsert)
        with pytest.raises(BadRequestError):
            await DeploymentSettingsService(AsyncMock()).set_apns_key(
                actor_user_id=uuid4(),
                data=ApnsKeyUpdate.model_validate(
                    {
                        "key_id": "KEY1234567",
                        "team_id": "TEAM123456",
                        "topic": "com.acme.agenticos",
                        "private_key": "pasted the wrong file",
                    }
                ),
            )
        upsert.assert_not_called()
        _quiet.assert_not_called()

    async def test_clearing_empties_every_column_and_is_audited(
        self, monkeypatch: pytest.MonkeyPatch, _quiet: AsyncMock
    ) -> None:
        upsert = AsyncMock()
        monkeypatch.setattr(settings_module.deployment_settings_repo, "upsert", upsert)
        read = await DeploymentSettingsService(AsyncMock()).clear_apns_key(actor_user_id=uuid4())
        assert upsert.await_args.kwargs["update_data"] == dict.fromkeys(APNS_COLUMNS)
        assert read == ApnsRead(configured=False)
        _quiet.assert_awaited_once()


class TestReading:
    @pytest.mark.parametrize("row", [None, SimpleNamespace(apns_private_key=None)])
    async def test_no_key_is_not_configured(self, row: object) -> None:
        with patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=row)):
            service = ApnsService(AsyncMock())
            assert await service.read() == ApnsRead(configured=False)
            assert await service._key() is None

    async def test_a_key_reads_as_whose_it_is_never_the_key(self) -> None:
        with patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=_row())):
            read = await ApnsService(AsyncMock()).read()
        assert read.environment == "production" and read.topic == "com.acme.agenticos"
        assert "BEGIN" not in read.model_dump_json()


class TestDevices:
    async def test_an_iphone_is_kept_only_where_there_is_a_key(self) -> None:
        user_id = uuid4()
        upsert = AsyncMock()
        with (
            patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.device_repo.upsert", new=upsert),
            pytest.raises(BadRequestError),
        ):
            await ApnsService(AsyncMock()).register(user_id, TOKEN)
        upsert.assert_not_called()
        with (
            patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=_row())),
            patch(f"{MODULE}.device_repo.upsert", new=upsert),
        ):
            await ApnsService(AsyncMock()).register(user_id, TOKEN)
        assert upsert.await_args.kwargs == {"user_id": user_id, "token": TOKEN}

    async def test_forgetting_one_that_was_never_there_is_a_404(self) -> None:
        with (
            patch(f"{MODULE}.device_repo.delete_for_user", new=AsyncMock(return_value=False)),
            pytest.raises(NotFoundError),
        ):
            await ApnsService(AsyncMock()).unregister(uuid4(), TOKEN)
        with patch(f"{MODULE}.device_repo.delete_for_user", new=AsyncMock(return_value=True)):
            await ApnsService(AsyncMock()).unregister(uuid4(), TOKEN)

    async def test_nobody_has_an_iphone_to_push_to_without_a_key(self) -> None:
        who = {uuid4()}
        subscribed = AsyncMock(return_value=who)
        with (
            patch(f"{MODULE}.device_repo.subscribed", new=subscribed),
            patch(f"{MODULE}.device_repo.list_for_user", new=AsyncMock(return_value=[_device()])),
        ):
            with patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=None)):
                assert await ApnsService(AsyncMock()).subscribed(list(who)) == set()
            with patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=_row())):
                assert await ApnsService(AsyncMock()).subscribed(list(who)) == who
                assert await ApnsService(AsyncMock()).has_devices(uuid4())


class TestSending:
    async def _send(
        self, apple: _Apple, devices: list[MagicMock], *, row: object = None
    ) -> tuple[PushOutcome, AsyncMock, AsyncMock]:
        mark, delete = AsyncMock(), AsyncMock()
        with (
            patch(f"{MODULE}.device_repo.list_for_user", new=AsyncMock(return_value=devices)),
            patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=row or _row())),
            patch(f"{MODULE}.device_repo.mark_sent", new=mark),
            patch(f"{MODULE}.device_repo.delete_by_id", new=delete),
        ):
            outcome = await ApnsService(AsyncMock(), connect=apple.connect).send(uuid4(), MESSAGE)
        return outcome, mark, delete

    async def test_nothing_is_sent_without_an_iphone_or_without_a_key(self) -> None:
        apple = _Apple()
        assert (await self._send(apple, []))[0] == PushOutcome(sent=0, gone=0, failed=0)
        outcome, _, _ = await self._send(
            apple, [_device()], row=SimpleNamespace(apns_private_key=None)
        )
        assert outcome == PushOutcome(sent=0, gone=0, failed=0)
        assert apple.posts == []

    async def test_each_answer_is_counted_and_a_gone_iphone_forgotten(self) -> None:
        devices = [_device() for _ in range(6)]
        apple = _Apple(
            ApnsAnswer(200, None),
            ApnsAnswer(410, "Unregistered"),
            ApnsAnswer(400, "BadDeviceToken"),
            ApnsAnswer(429, "TooManyRequests"),
            ApnsAnswer(403, "ExpiredProviderToken"),
            httpx.ConnectError("no route"),
        )
        outcome, mark, delete = await self._send(apple, devices)
        assert outcome == PushOutcome(sent=1, gone=2, failed=3)
        assert mark.await_args.args[1] == devices[0].id
        assert isinstance(mark.await_args.args[2], datetime)
        assert [call.args[1] for call in delete.await_args_list] == [devices[1].id, devices[2].id]

    async def test_the_message_is_apples_shape_signed_by_the_organizations_key(self) -> None:
        apple = _Apple(ApnsAnswer(200, None))
        await self._send(apple, [_device()])
        url, headers, body = apple.posts[0]
        assert url == f"https://api.push.apple.com/3/device/{TOKEN}"
        assert headers["apns-topic"] == "com.acme.agenticos"
        assert headers["apns-push-type"] == "alert"
        assert len(headers["apns-collapse-id"]) == 64
        payload = json.loads(body)
        assert payload["aps"]["alert"] == {"title": "Acme", "body": "Run done"}
        assert payload["url"] == "/runs?run=r1"
        token = headers["authorization"].removeprefix("bearer ")
        assert jwt.get_unverified_header(token)["kid"] == "KEY1234567"
        public = load_pem_private_key(P8.encode(), password=None).public_key()
        assert jwt.decode(token, public, algorithms=["ES256"])["iss"] == "TEAM123456"

    async def test_a_sandbox_key_goes_to_apples_development_service(self) -> None:
        apple = _Apple(ApnsAnswer(200, None))
        await self._send(apple, [_device()], row=_row(sandbox=True))
        assert apple.posts[0][0].startswith("https://api.sandbox.push.apple.com/")

    async def test_the_provider_token_is_reused_until_it_ages_or_apple_refuses_it(self) -> None:
        apple = _Apple(
            ApnsAnswer(200, None),
            ApnsAnswer(200, None),
            ApnsAnswer(403, "InvalidProviderToken"),
            ApnsAnswer(200, None),
        )
        with patch(f"{MODULE}.time.time", return_value=1_000_000.0):
            await self._send(apple, [_device(), _device()])
        first, second = (post[1]["authorization"] for post in apple.posts)
        assert first == second
        later = 1_000_000.0 + apns.PROVIDER_TOKEN_SECONDS + 1
        with patch(f"{MODULE}.time.time", return_value=later):
            await self._send(apple, [_device()])
            await self._send(apple, [_device()])
        assert apple.posts[2][1]["authorization"] != first
        # Refused, so signed afresh rather than sent stale for the rest of the hour.
        assert apple.posts[3][1]["authorization"] != first
        assert apns._provider_tokens


class TestTheTransport:
    async def test_it_reads_apples_reason_and_survives_a_body_that_is_not_json(self) -> None:
        answers = iter(
            [
                httpx.Response(200),
                httpx.Response(400, json={"reason": "BadDeviceToken"}),
                httpx.Response(500, content=b"<html>"),
                httpx.Response(403, json=["odd"]),
            ]
        )
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(answers)))
        transport = apns._HttpxTransport(client)
        seen = [
            await transport.post("https://api.push.apple.com/3/device/x", headers={}, body=b"{}")
            for _ in range(4)
        ]
        await client.aclose()
        assert seen == [
            ApnsAnswer(200, None),
            ApnsAnswer(400, "BadDeviceToken"),
            ApnsAnswer(500, None),
            ApnsAnswer(403, None),
        ]

    async def test_the_real_one_is_an_http2_client(self) -> None:
        made: list[dict[str, object]] = []
        real = httpx.AsyncClient

        def client(**kwargs: object) -> httpx.AsyncClient:
            made.append(kwargs)
            return real()

        with patch(f"{MODULE}.httpx.AsyncClient", side_effect=client):
            async with http2_transport() as transport:
                assert isinstance(transport, apns._HttpxTransport)
        assert made == [{"http2": True, "timeout": apns.SEND_TIMEOUT_SECONDS}]


class TestEverywhere:
    async def test_a_send_adds_up_browsers_and_iphones(self) -> None:
        web = MagicMock(send=AsyncMock(return_value=PushOutcome(sent=1, gone=0, failed=1)))
        apple = MagicMock(send=AsyncMock(return_value=PushOutcome(sent=2, gone=1, failed=0)))
        service = PushService(AsyncMock(), web=web, apple=apple)
        assert await service.send(uuid4(), MESSAGE) == PushOutcome(sent=3, gone=1, failed=1)

    async def test_subscribed_is_whoever_has_either(self) -> None:
        a, b = uuid4(), uuid4()
        apple = MagicMock(subscribed=AsyncMock(return_value={b}))
        with patch("app.services.push.push_repo.subscribed", new=AsyncMock(return_value={a})):
            assert await PushService(AsyncMock(), web=MagicMock(), apple=apple).subscribed(
                [a, b]
            ) == {a, b}

    async def test_a_test_needs_a_browser_or_an_iphone(self) -> None:
        web = MagicMock(
            has_subscriptions=AsyncMock(return_value=False),
            send=AsyncMock(return_value=PushOutcome(sent=0, gone=0, failed=0)),
        )
        apple = MagicMock(
            has_devices=AsyncMock(return_value=False),
            send=AsyncMock(return_value=PushOutcome(sent=1, gone=0, failed=0)),
        )
        service = PushService(AsyncMock(), web=web, apple=apple)
        with pytest.raises(NotFoundError):
            await service.send_test(uuid4(), app_name="Acme")
        apple.has_devices.return_value = True
        assert (await service.send_test(uuid4(), app_name="Acme")).sent == 1
        assert apple.send.await_args.args[1].title == "Acme"

    def test_it_builds_both_senders_by_default(self) -> None:
        service = PushService(AsyncMock())
        assert isinstance(service.apple, ApnsService)
