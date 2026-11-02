"""An outbound media capability opens only a bounded, short-lived staged copy."""

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.api.deps import get_sms_media_service
from app.core.exceptions import NotFoundError
from app.core.logging import redact_secret_paths
from app.main import app
from app.services.channels.base import OutgoingAttachment
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.sms_media import (
    TTL_SECONDS,
    SmsMediaService,
    open_media_store,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _redis():
    values: dict[str, str] = {}

    async def put(key, value, ttl=None):
        values[key] = value
        return True

    redis = MagicMock(
        set=AsyncMock(side_effect=put), get=AsyncMock(side_effect=lambda key: values.get(key))
    )
    return redis, values


def _file():
    return OutgoingAttachment(
        filename="../../raport-ż\r\n.csv", content=b"a,b\n1,2", mime_type="text/csv"
    )


async def test_staging_never_exposes_the_original_filename_or_hands_other_files_the_same_credential():
    redis, values = _redis()
    service = SmsMediaService(redis)
    with patch(
        "app.services.channels.sms_media.settings.PUBLIC_BASE_URL", "https://agenticos.example"
    ):
        first, other = await service.stage(_file()), await service.stage(_file())
    parsed = urlsplit(first)
    identifier, token = UUID(parsed.path.rsplit("/", 1)[-1]), parse_qs(parsed.query)["token"][0]
    stored = await SmsMediaService(redis).open(identifier, token)
    assert stored.content == _file().content
    assert stored.mime_type == "text/csv"
    assert len(stored.filename) <= 20 and "/" not in stored.filename and "\r" not in stored.filename
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert all(token not in raw for raw in values.values())
    assert token not in redact_secret_paths(first)
    assert redis.set.await_args.kwargs["ttl"] == TTL_SECONDS
    other_id = UUID(urlsplit(other).path.rsplit("/", 1)[-1])
    for bad_id, bad_token in [
        (other_id, token),
        (identifier, "0" * 64),
        (identifier, None),
        (identifier, "invalid"),
        (uuid4(), token),
    ]:
        with pytest.raises(NotFoundError):
            await service.open(bad_id, bad_token)
    values.clear()
    with pytest.raises(NotFoundError):
        await service.open(identifier, token)


@pytest.mark.parametrize(
    "base",
    [
        "http://localhost:8000",
        "https://user:password@host",
        "https://host?secret=x",
        "https://host/#fragment",
        "https://",
    ],
)
async def test_unusable_public_media_addresses_are_refused_before_storing_bytes(base: str):
    redis, _ = _redis()
    with (
        patch("app.services.channels.sms_media.settings.PUBLIC_BASE_URL", base),
        pytest.raises(ChannelNotConfigured),
    ):
        await SmsMediaService(redis).stage(_file())
    redis.set.assert_not_awaited()


async def test_get_and_head_open_only_the_staged_copy_and_do_not_consume_the_credential(
    client: AsyncClient,
):
    redis, values = _redis()
    service = SmsMediaService(redis)
    with patch(
        "app.services.channels.sms_media.settings.PUBLIC_BASE_URL", "https://agenticos.example"
    ):
        url = await service.stage(_file())
    app.dependency_overrides[get_sms_media_service] = lambda: service
    parsed = urlsplit(url)
    path = parsed.path + "?" + parsed.query
    head = await client.head(path)
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(len(_file().content))
    got = await client.get(path)
    assert got.status_code == 200 and got.content == _file().content
    assert got.headers["content-type"].startswith("text/csv")
    assert got.headers["cache-control"] == "no-store"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "inline; filename=" in got.headers["content-disposition"]
    assert (await client.get(parsed.path)).status_code == 404
    assert (await client.get(parsed.path, params={"token": "0" * 64})).status_code == 404
    values.clear()
    assert (await client.get(path)).status_code == 404


@pytest.mark.parametrize("failure", [None, "connect", "send", "cancel"])
async def test_senders_close_their_store_on_success_failure_and_cancellation(failure):
    redis = MagicMock(connect=AsyncMock(), close=AsyncMock())
    if failure == "connect":
        redis.connect.side_effect = RuntimeError("unavailable")
    with patch("app.services.channels.sms_media.RedisClient", return_value=redis):
        if failure is None:
            async with open_media_store() as service:
                assert service.redis is redis
        else:
            with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
                async with open_media_store():
                    if failure == "cancel":
                        raise asyncio.CancelledError
                    raise RuntimeError("send failed")
    redis.close.assert_awaited_once()
