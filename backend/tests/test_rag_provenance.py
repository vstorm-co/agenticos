"""Deriving a document's calendar date for the FA-039 doc_date filter."""

from datetime import UTC, date, datetime

from app.services.rag.provenance import iso_doc_date, to_utc_date


class TestToUtcDate:
    def test_none_is_none(self):
        assert to_utc_date(None) is None

    def test_an_aware_datetime_is_converted_to_utc_before_the_date_is_taken(self):
        # 23:30 in +02:00 is 21:30 UTC on the same day; a +02:00 00:30 rolls back.
        assert to_utc_date(datetime(2025, 3, 2, 0, 30, tzinfo=_tz(2))) == date(2025, 3, 1)

    def test_a_naive_datetime_is_read_as_utc(self):
        naive = datetime(2025, 3, 2, 12, 0)  # noqa: DTZ001 - the naive case is the point
        assert to_utc_date(naive) == date(2025, 3, 2)

    def test_a_plain_date_passes_through(self):
        assert to_utc_date(date(2025, 1, 1)) == date(2025, 1, 1)

    def test_a_posix_mtime_is_read_as_utc(self):
        assert to_utc_date(0) == date(1970, 1, 1)


class TestIsoDocDate:
    def test_the_first_resolvable_candidate_wins(self):
        assert iso_doc_date(None, date(2024, 6, 1), date(2020, 1, 1)) == "2024-06-01"

    def test_falls_back_to_ingestion_time_when_nothing_resolves(self):
        assert iso_doc_date(None, None) == datetime.now(UTC).date().isoformat()


def _tz(hours: int):
    from datetime import timedelta, timezone

    return timezone(timedelta(hours=hours))
