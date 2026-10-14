"""Call minutes for the dashboard and the organization's Voice card (#54)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.services.voice import VoiceUsageService

pytestmark = pytest.mark.anyio

_START = datetime(2026, 9, 1, tzinfo=UTC)
_END = datetime(2026, 10, 1, tzinfo=UTC)


async def test_usage_sums_the_window_and_reads_the_month_against_the_limit(monkeypatch):
    by_agent = AsyncMock(
        return_value=[(uuid4(), "Support", 600, 3), (uuid4(), "Sales", 120, 1), (None, None, 60, 1)]
    )
    monkeypatch.setattr("app.services.voice.usage.voice_call_repo.usage_by_agent", by_agent)
    monkeypatch.setattr(
        "app.services.voice.usage.voice_call_repo.seconds_since", AsyncMock(return_value=900)
    )
    monkeypatch.setattr(
        "app.services.voice.usage.organization_repo.get_by_id",
        AsyncMock(return_value=SimpleNamespace(voice_monthly_minutes=600)),
    )

    usage = await VoiceUsageService(MagicMock()).usage(
        SimpleNamespace(organization_id=uuid4()), start=_START, end=_END
    )

    # A deleted agent's calls still count, so the totals reconcile with the rows.
    assert (usage.seconds, usage.calls) == (780, 5)
    assert (usage.month_seconds, usage.monthly_minutes) == (900, 600)
    assert [a.agent_name for a in usage.by_agent] == ["Support", "Sales", None]
    assert (by_agent.await_args.kwargs["start"], by_agent.await_args.kwargs["end"]) == (
        _START,
        _END,
    )


async def test_a_window_without_a_zone_is_read_as_utc(monkeypatch):
    by_agent = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.voice.usage.voice_call_repo.usage_by_agent", by_agent)
    monkeypatch.setattr(
        "app.services.voice.usage.voice_call_repo.seconds_since", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        "app.services.voice.usage.organization_repo.get_by_id", AsyncMock(return_value=None)
    )

    usage = await VoiceUsageService(MagicMock()).usage(
        SimpleNamespace(organization_id=uuid4()),
        start=_START.replace(tzinfo=None),
        end=_END.replace(tzinfo=None),
    )

    assert by_agent.await_args.kwargs["start"] == _START
    assert (usage.seconds, usage.calls, usage.by_agent, usage.monthly_minutes) == (0, 0, [], None)


async def test_a_window_that_ends_before_it_starts_is_refused(monkeypatch):
    by_agent = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.voice.usage.voice_call_repo.usage_by_agent", by_agent)

    with pytest.raises(ValidationError):
        await VoiceUsageService(MagicMock()).usage(
            SimpleNamespace(organization_id=uuid4()), start=_END, end=_START
        )
    by_agent.assert_not_awaited()
