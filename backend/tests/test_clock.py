"""Tests for the clock capability.

It stopped being a tool and became instructions, and the tests changed shape
with it. What is worth pinning now is not that a function returns a dictionary
but that the line reaching the model is correct, is in the caller's timezone,
and is rebuilt for each request rather than frozen when the agent was built.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.agents.capabilities.clock import Clock, ClockConfig
from app.agents.capabilities.clock import _capability as clock_module


def _instruction(clock: Clock) -> str:
    """The line as the model would receive it."""
    return clock.get_instructions()(MagicMock())


class TestInstructions:
    def test_the_agent_is_told_the_time_without_having_to_ask(self):
        """The whole point: no tool call, no round trip, no chance to skip it."""
        assert "The current date and time is" in _instruction(Clock())

    def test_the_date_is_iso_so_the_model_can_do_arithmetic_on_it(self):
        """ "14 days from 2026-07-27" goes better than from "27 July 2026"."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        assert today in _instruction(Clock())

    def test_the_zone_is_named_so_the_offset_is_not_a_guess(self):
        assert "(UTC)" in _instruction(Clock())

    def test_the_capability_contributes_no_tools(self):
        """A tool here would only offer the model a slower way to learn this."""
        assert Clock().get_toolset() is None


class TestTimezone:
    def test_a_configured_zone_is_what_the_agent_reads(self):
        warsaw = _instruction(Clock(timezone="Europe/Warsaw"))

        assert "Europe/Warsaw" not in warsaw  # the abbreviation, not the id
        assert "CET" in warsaw or "CEST" in warsaw

    def test_two_zones_can_disagree_about_what_day_it_is(self):
        """The reason this is configuration at all.

        Asserted at a fixed instant, not at "now": Auckland and Honolulu are
        22 hours apart, so they share a date for one hour in every 24 - and a
        test that reads the wall clock fails in exactly that hour, which is a
        flake I wrote and then hit.

        23:30 UTC is inside that gap for Warsaw too, which is the case worth
        protecting: an agent there reporting the UTC date is a day behind, and
        nobody notices until it schedules something.
        """
        instant = datetime(2026, 7, 27, 23, 30, tzinfo=UTC)

        warsaw = instant.astimezone(ZoneInfo("Europe/Warsaw"))
        auckland = instant.astimezone(ZoneInfo("Pacific/Auckland"))

        assert instant.date() != warsaw.date()
        assert instant.date() != auckland.date()
        assert Clock(timezone="Europe/Warsaw")._zone == ZoneInfo("Europe/Warsaw")

    def test_utc_is_the_default(self):
        assert Clock().now().utcoffset() == datetime.now(UTC).utcoffset()

    def test_an_unknown_zone_is_refused_at_build_time(self):
        """A bad zone should fail in the Builder, not mid-run in front of a user."""
        with pytest.raises(ValueError, match="Unknown timezone"):
            Clock(timezone="Mars/Olympus")

    def test_a_zone_that_is_not_a_zone_at_all_is_refused_the_same_way(self):
        """Configuration arrives as JSON; the annotation guarantees nothing."""
        with pytest.raises(ValueError, match="Unknown timezone"):
            Clock(timezone="../../etc/passwd")


class TestPerRequest:
    def test_the_time_is_read_when_the_request_runs_not_when_the_agent_was_built(self):
        """A conversation open for an hour must not keep repeating its first minute."""
        clock = Clock()
        first = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
        second = datetime(2026, 7, 27, 10, 30, tzinfo=UTC)
        line = clock.get_instructions()

        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(clock, "now", lambda: first)
            early = line(MagicMock())
            patched.setattr(clock, "now", lambda: second)
            late = line(MagicMock())

        assert "09:00:00" in early
        assert "10:30:00" in late

    def test_the_module_reads_a_real_clock(self):
        """Guards the substitution the test above relies on being a substitution."""
        assert clock_module.datetime is datetime


class TestConfig:
    def test_the_builder_passes_the_configured_zone_through(self):
        from app.agents.capabilities import CapabilityBinding, build

        built = build([CapabilityBinding(capability_id="clock", config={"timezone": "Asia/Tokyo"})])

        assert isinstance(built[0], Clock)
        assert built[0].timezone == "Asia/Tokyo"

    def test_no_config_means_utc(self):
        assert ClockConfig().timezone == "UTC"

    def test_a_zone_longer_than_any_real_one_is_refused_by_the_schema(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ClockConfig(timezone="x" * 65)
