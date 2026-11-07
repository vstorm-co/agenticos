"""A background sender's MMS staging is readable by a separate API Redis client."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from app.clients.redis import RedisClient
from app.core.exceptions import NotFoundError
from app.services.channels.base import OutgoingAttachment
from app.services.channels.sms_media import TTL_SECONDS, SmsMediaService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_media_handoff_survives_sender_disconnect_and_expires_in_shared_redis():
    sender, api = RedisClient(), RedisClient()
    await sender.connect()
    await api.connect()
    key = None
    try:
        with patch(
            "app.services.channels.sms_media.settings.PUBLIC_BASE_URL", "https://agenticos.example"
        ):
            url = await SmsMediaService(sender).stage(
                OutgoingAttachment(filename="report.csv", mime_type="text/csv", content=b"a,b\n1,2")
            )
        parsed = urlsplit(url)
        identifier = UUID(parsed.path.rsplit("/", 1)[-1])
        token = parse_qs(parsed.query)["token"][0]
        key = f"channel:sms:outbound-media:{identifier}"
        assert 0 < await api.raw.ttl(key) <= TTL_SECONDS
        await sender.close()
        opened = await SmsMediaService(api).open(identifier, token)
        assert opened.content == b"a,b\n1,2"
        await api.raw.expire(key, 0)
        with pytest.raises(NotFoundError):
            await SmsMediaService(api).open(identifier, token)
    finally:
        if key is not None:
            await api.delete(key)
        await api.close()
        await sender.close()
