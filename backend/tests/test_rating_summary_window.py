"""The window the deployment-wide rating summary answers for.

This summary used to take a number of days and count back from now, which made
a whole class of question unaskable: the dashboard's "last month" is a period
that has already ended, and a trailing window always ends today. The card
therefore showed the last thirty days whatever the filter said, and the bar
chart carried today's date under a heading naming July.

It now takes the same inclusive dates as the organization-scoped summary and
resolves them the same way, so one filter means one thing on both cards.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.repositories import message_rating as rating_repo
from app.services.message_rating import MessageRatingService

pytestmark = pytest.mark.anyio

_EMPTY: dict[str, Any] = {
    "total_ratings": 0,
    "like_count": 0,
    "dislike_count": 0,
    "average_rating": 0.0,
    "with_comments": 0,
    "ratings_by_day": [],
}


def _service(monkeypatch: pytest.MonkeyPatch) -> tuple[MessageRatingService, AsyncMock]:
    summary = AsyncMock(return_value=dict(_EMPTY))
    monkeypatch.setattr(rating_repo, "get_rating_summary", summary)
    return MessageRatingService(AsyncMock()), summary


async def test_a_month_that_has_already_ended_is_the_window_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, summary = _service(monkeypatch)

    await service.get_summary(from_date=date(2026, 7, 1), to_date=date(2026, 7, 31))

    assert summary.call_args.kwargs["start"] == datetime(2026, 7, 1, tzinfo=UTC)
    # Half-open, and inclusive `to` means the whole of the 31st counts.
    assert summary.call_args.kwargs["end"] == datetime(2026, 8, 1, tzinfo=UTC)


async def test_no_dates_still_means_the_last_thirty_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, summary = _service(monkeypatch)

    await service.get_summary()

    start = summary.call_args.kwargs["start"]
    end = summary.call_args.kwargs["end"]
    assert (end - start).days == 30
    assert end.date() == datetime.now(UTC).date() + timedelta(days=1)


async def test_the_summary_is_returned_as_the_schema_the_route_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, summary = _service(monkeypatch)
    summary.return_value = {
        **_EMPTY,
        "total_ratings": 3,
        "like_count": 2,
        "dislike_count": 1,
        "ratings_by_day": [{"date": "2026-07-04", "likes": 2, "dislikes": 1}],
    }

    result = await service.get_summary(from_date=date(2026, 7, 1), to_date=date(2026, 7, 31))

    assert result.total_ratings == 3
    assert result.ratings_by_day == [{"date": "2026-07-04", "likes": 2, "dislikes": 1}]
