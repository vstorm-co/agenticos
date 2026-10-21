"""Cron expressions shared by agent triggers and eval suites."""

from datetime import UTC, datetime

import pytest

from app.core.cron import cron_fires, cron_has_next, cron_next


class TestCronHasNext:
    @pytest.mark.parametrize("expression", ["0 9 * * *", "*/15 * * * 1-5", "0 0 1 */3 *"])
    def test_a_five_field_expression_that_fires_is_accepted(self, expression: str) -> None:
        assert cron_has_next(expression)

    @pytest.mark.parametrize(
        "expression",
        [
            "* * * * * *",  # a seconds column the minute sweep cannot honour
            "0 9 * *",
            "not a cron",
            "a b c d e",  # five fields, none of them cron
            "0 0 31 2 *",  # valid syntax, but February never has a 31st
        ],
    )
    def test_an_expression_that_never_fires_here_is_refused(self, expression: str) -> None:
        assert not cron_has_next(expression)


class TestCronNext:
    def test_utc_is_the_default_zone(self) -> None:
        now = datetime(2026, 10, 19, 8, 30, tzinfo=UTC)
        assert cron_next("0 9 * * *", now=now) == datetime(2026, 10, 19, 9, 0, tzinfo=UTC)

    def test_the_next_fire_is_strictly_after_now(self) -> None:
        now = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
        assert cron_next("0 9 * * *", now=now) == datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

    def test_the_expression_is_read_on_the_zones_wall_clock(self) -> None:
        now = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
        # Nine in Warsaw in summer is seven in UTC.
        assert cron_next("0 9 * * *", now=now, time_zone="Europe/Warsaw") == datetime(
            2026, 7, 1, 7, 0, tzinfo=UTC
        )

    def test_the_wall_clock_holds_across_a_clock_change(self) -> None:
        # Poland leaves summer time on 2026-10-25, so nine o'clock moves from 07:00
        # to 08:00 UTC between the two Mondays either side of it.
        before = cron_next(
            "0 9 * * 1", now=datetime(2026, 10, 18, 12, 0, tzinfo=UTC), time_zone="Europe/Warsaw"
        )
        after = cron_next("0 9 * * 1", now=before, time_zone="Europe/Warsaw")
        assert before == datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
        assert after == datetime(2026, 10, 26, 8, 0, tzinfo=UTC)

    def test_the_answer_is_in_utc(self) -> None:
        now = datetime(2026, 10, 19, 8, 30, tzinfo=UTC)
        assert cron_next("0 9 * * *", now=now, time_zone="Asia/Tokyo").tzinfo is UTC


class TestCronFires:
    start = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    end = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)

    def test_a_sparse_schedule_is_counted_fire_by_fire(self) -> None:
        assert cron_fires("0 6 * * *", start=self.start, end=self.end, sample=100) == 30

    def test_a_dense_schedule_is_extrapolated_from_its_first_fires(self) -> None:
        """Thirty days of every minute is 43,200 fires; walking them would hold the worker."""
        assert cron_fires("* * * * *", start=self.start, end=self.end, sample=100) == 43_200
