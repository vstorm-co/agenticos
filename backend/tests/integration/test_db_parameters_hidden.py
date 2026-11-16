"""A failed statement's values stay out of the error and its log record."""

import logging

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.logging import PiiRedactionFilter
from app.db.models.channel_identity import ChannelIdentity
from app.db.session import _managed_session, async_session_maker

pytestmark = pytest.mark.anyio

# A WhatsApp-style business-scoped id, which no other redaction pattern matches.
VALUE = "US.4815162342"


@pytest.mark.security
async def test_a_failed_insert_does_not_carry_its_values(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    caught: DBAPIError | None = None
    with caplog.at_level(logging.ERROR, logger="app.db.session"):
        try:
            async with _managed_session(async_session_maker) as session:
                session.add(ChannelIdentity(platform="whatsapp", platform_user_id=VALUE))
                await session.flush()
                session.add(ChannelIdentity(platform="whatsapp", platform_user_id=VALUE))
                await session.flush()
        except DBAPIError as exc:
            caught = exc

    assert caught is not None
    assert "parameters hidden" in str(caught)
    assert "INSERT INTO channel_identities" in str(caught)
    assert VALUE not in str(caught)

    record = next(r for r in caplog.records if r.name == "app.db.session")
    PiiRedactionFilter().filter(record)
    assert record.exc_text is not None
    assert VALUE not in record.exc_text
    # The rest of the chain stays readable.
    assert "[SQL: INSERT INTO channel_identities" in record.exc_text
    assert "UniqueViolationError" in record.exc_text
