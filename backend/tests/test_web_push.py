"""Web Push (#2097): the endpoint allowlist, the deployment's signing key and a send."""

import base64
from collections.abc import Iterator
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pywebpush import WebPushException

from app.core.exceptions import AppException, NotFoundError
from app.core.vault import VaultScope, seal, unseal
from app.schemas.push import PushSubscriptionCreate, push_endpoint
from app.services import web_push
from app.services.web_push import PushMessage, WebPushService

pytestmark = pytest.mark.anyio

MODULE = "app.services.web_push"
KEYS = {"p256dh": "BPk-Kd3_d0", "auth": "c2VjcmV0"}


def _decoded(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class TestTheEndpointAllowlist:
    @pytest.mark.parametrize(
        "url",
        [
            "https://fcm.googleapis.com/fcm/send/abc",
            "https://updates.push.services.mozilla.com/wpush/v2/abc",
            "https://web.push.apple.com/abc",
            "https://wns2-par02p.notify.windows.com/w/?token=abc",
        ],
    )
    def test_a_browser_push_service_is_accepted(self, url: str) -> None:
        assert push_endpoint(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            "http://fcm.googleapis.com/fcm/send/abc",
            "https://169.254.169.254/latest",
            "https://internal.acme.local/hook",
            "https://fcm.googleapis.com.evil.example/abc",
            "https://user:pw@fcm.googleapis.com/abc",
            "https://fcm.googleapis.com:8443/abc",
        ],
    )
    def test_anything_else_is_refused(self, url: str) -> None:
        with pytest.raises(ValueError):
            push_endpoint(url)
        with pytest.raises(ValidationError):
            PushSubscriptionCreate.model_validate({"endpoint": url, "keys": KEYS})


def test_a_new_key_is_a_p256_pair_as_web_push_spells_it() -> None:
    private, public = web_push._new_key()
    assert len(_decoded(private)) == 32
    raw = _decoded(public)
    assert len(raw) == 65 and raw[0] == 4


def test_the_subject_is_the_console_where_it_is_public_and_the_sender_otherwise() -> None:
    with patch.object(web_push.settings, "FRONTEND_URL", "https://agenticos.acme.com"):
        assert web_push._subject() == "https://agenticos.acme.com"
    with (
        patch.object(web_push.settings, "FRONTEND_URL", "http://localhost:3000"),
        patch.object(web_push.settings, "EMAIL_FROM", "noreply@acme.com"),
    ):
        assert web_push._subject() == "mailto:noreply@acme.com"


class TestTheSigningKey:
    async def test_it_is_made_on_first_use_and_claimed_once(self) -> None:
        claimed: dict[str, object] = {}

        async def claim(_db, *, private_key: str, public_key: str, key_version: int):
            claimed.update(private_key=private_key, public_key=public_key)
            return SimpleNamespace(
                vapid_private_key=private_key,
                vapid_public_key=public_key,
                vapid_key_version=key_version,
            )

        with (
            patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.deployment_repo.claim_vapid_key", new=claim),
        ):
            public = await WebPushService(AsyncMock()).public_key()
        assert public == claimed["public_key"]
        # Stored sealed for the deployment, never as the raw scalar.
        stored = str(claimed["private_key"])
        assert len(unseal(stored, scope=VaultScope.deployment())) == 43
        with pytest.raises(AppException):
            unseal(stored, scope=VaultScope.user(uuid4()))

    async def test_a_key_already_there_is_used_and_never_replaced(self) -> None:
        private, public = web_push._new_key()
        sealed = seal(private, scope=VaultScope.deployment())
        row = SimpleNamespace(
            vapid_private_key=sealed.ciphertext,
            vapid_public_key=public,
            vapid_key_version=sealed.key_version,
        )
        claim = AsyncMock()
        with (
            patch(f"{MODULE}.deployment_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{MODULE}.deployment_repo.claim_vapid_key", new=claim),
        ):
            assert await WebPushService(AsyncMock())._signing_key() == (private, public)
        claim.assert_not_called()


def _subscription(endpoint: str = "https://fcm.googleapis.com/fcm/send/a") -> MagicMock:
    return MagicMock(id=uuid4(), endpoint=endpoint, p256dh=KEYS["p256dh"], auth=KEYS["auth"])


def _refusal(status: int) -> WebPushException:
    return WebPushException("refused", response=SimpleNamespace(status=status))


class TestSending:
    @pytest.fixture
    def service(self) -> Iterator[WebPushService]:
        with patch.object(
            WebPushService, "_signing_key", new=AsyncMock(return_value=web_push._new_key())
        ):
            yield WebPushService(AsyncMock())

    async def test_nobody_subscribed_is_nothing_sent(self, service: WebPushService) -> None:
        with patch(f"{MODULE}.push_repo.list_for_user", new=AsyncMock(return_value=[])):
            outcome = await service.send(uuid4(), PushMessage("t", "b", "/runs", "n1"))
        assert (outcome.sent, outcome.gone, outcome.failed) == (0, 0, 0)

    async def test_each_browser_is_sent_to_forgotten_when_gone_and_counted_when_refused(
        self, service: WebPushService
    ) -> None:
        ok, gone, refused, slow = (_subscription() for _ in range(4))
        sends = AsyncMock(side_effect=[None, _refusal(410), _refusal(500), TimeoutError()])
        with (
            patch(
                f"{MODULE}.push_repo.list_for_user",
                new=AsyncMock(return_value=[ok, gone, refused, slow]),
            ),
            patch(f"{MODULE}.webpush_async", new=sends),
            patch(f"{MODULE}.push_repo.delete_by_id", new=AsyncMock()) as delete,
            patch(f"{MODULE}.push_repo.mark_sent", new=AsyncMock()) as mark,
        ):
            outcome = await service.send(uuid4(), PushMessage("Acme", "Run done", "/runs", "n1"))
        assert (outcome.sent, outcome.gone, outcome.failed) == (1, 1, 2)
        delete.assert_awaited_once()
        assert delete.await_args.args[1] == gone.id
        assert mark.await_args.args[1] == ok.id
        assert isinstance(mark.await_args.args[2], datetime)
        first = sends.await_args_list[0].kwargs
        assert first["subscription_info"]["endpoint"] == ok.endpoint
        assert '"url": "/runs"' in first["data"]
        assert first["ttl"] == web_push.TTL_SECONDS

    async def test_a_test_needs_a_subscribed_browser(self, service: WebPushService) -> None:
        with (
            patch(f"{MODULE}.push_repo.list_for_user", new=AsyncMock(return_value=[])),
            pytest.raises(NotFoundError),
        ):
            await service.send_test(uuid4(), app_name="Acme")
        with (
            patch(
                f"{MODULE}.push_repo.list_for_user", new=AsyncMock(return_value=[_subscription()])
            ),
            patch(f"{MODULE}.webpush_async", new=AsyncMock()),
            patch(f"{MODULE}.push_repo.mark_sent", new=AsyncMock()),
        ):
            outcome = await service.send_test(uuid4(), app_name="Acme")
        assert outcome.sent == 1


class TestSubscribing:
    async def test_a_browser_is_kept_and_forgotten_on_request(self) -> None:
        user_id = uuid4()
        subscription = PushSubscriptionCreate.model_validate(
            {"endpoint": "https://fcm.googleapis.com/fcm/send/a", "keys": KEYS}
        )
        with patch(f"{MODULE}.push_repo.upsert", new=AsyncMock()) as upsert:
            await WebPushService(AsyncMock()).subscribe(user_id, subscription, user_agent="Chrome")
        assert upsert.await_args.kwargs["user_id"] == user_id
        assert upsert.await_args.kwargs["auth"] == KEYS["auth"]
        with patch(f"{MODULE}.push_repo.delete_for_user", new=AsyncMock(return_value=True)):
            await WebPushService(AsyncMock()).unsubscribe(user_id, subscription.endpoint)
        with (
            patch(f"{MODULE}.push_repo.delete_for_user", new=AsyncMock(return_value=False)),
            pytest.raises(NotFoundError),
        ):
            await WebPushService(AsyncMock()).unsubscribe(user_id, subscription.endpoint)
