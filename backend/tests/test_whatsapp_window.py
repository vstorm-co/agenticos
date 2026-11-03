"""The 24-hour window's pure rules (#2076)."""

from datetime import UTC, datetime, timedelta

from app.services.channels.whatsapp_format import utf16_units
from app.services.channels.whatsapp_window import (
    PREVIEW_ENDING,
    PREVIEW_UNITS,
    closure_is_news,
    fits,
    flatten,
    preview,
    window_open,
)

T = datetime(2026, 11, 4, 12, tzinfo=UTC)


def test_the_window_is_open_until_five_minutes_before_24_hours() -> None:
    kwargs = {"last_inbound_at": T, "closed_at": None}
    assert window_open(**kwargs, now=T + timedelta(hours=23, minutes=54, seconds=59))
    assert not window_open(**kwargs, now=T + timedelta(hours=23, minutes=55))


def test_no_message_means_a_closed_window() -> None:
    assert not window_open(last_inbound_at=None, closed_at=None, now=T)


def test_a_closure_since_the_latest_message_closes_the_window() -> None:
    now = T + timedelta(hours=1)
    assert not window_open(last_inbound_at=T, closed_at=T + timedelta(seconds=1), now=now)
    assert window_open(last_inbound_at=T, closed_at=T - timedelta(seconds=1), now=now)


def test_a_closure_older_than_the_latest_message_is_not_news() -> None:
    second = timedelta(seconds=1)
    assert not closure_is_news(last_inbound_at=T, closed_at=None, at=T - second)
    assert closure_is_news(last_inbound_at=T, closed_at=None, at=T + second)
    assert not closure_is_news(last_inbound_at=T, closed_at=T + second, at=T + 2 * second)
    assert closure_is_news(last_inbound_at=T, closed_at=T - second, at=T + second)
    assert closure_is_news(last_inbound_at=None, closed_at=None, at=T)
    assert not closure_is_news(last_inbound_at=None, closed_at=T, at=T)


def test_flatten_makes_one_line_with_single_spaces() -> None:
    assert flatten("a\n\nb\t\tc     d ") == "a b c d"


def test_the_fit_counts_utf16_units_with_the_fixed_text() -> None:
    def fit(text: str) -> bool:
        return fits(text, fixed_length=24, has_files=False)

    assert fit("a" * 1000)
    assert not fit("a" * 1001)
    assert fit("👍" * 500)
    assert not fit("👍" * 501)
    assert fit("a\n" * 400)


def test_files_or_empty_text_never_fit() -> None:
    assert not fits("short", fixed_length=0, has_files=True)
    assert not fits("", fixed_length=0, has_files=False)
    assert not fits(" \n\t ", fixed_length=0, has_files=False)


def test_the_preview_is_short_one_line_and_ends_with_the_invitation() -> None:
    text = "".join(f"line {n} of the answer\n" for n in range(100))
    assert len(text) > 2000
    result = preview(text)
    assert utf16_units(result) <= PREVIEW_UNITS + utf16_units(PREVIEW_ENDING)
    assert result.endswith(PREVIEW_ENDING)
    assert "\n" not in result
