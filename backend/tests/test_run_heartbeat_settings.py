"""The stale-run ceiling against the heartbeat that keeps a live run off it (#2301)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(("beat", "ceiling"), [(60.0, 120.0), (15.0, 44.0)])
def test_a_ceiling_a_live_runs_heartbeat_cannot_beat_is_refused(
    beat: float, ceiling: float
) -> None:
    """Codex on #2324: a run's first beat lands one interval in, so a ceiling that
    close ends live runs mid-call."""
    with pytest.raises(ValidationError, match="at least three"):
        Settings(RUN_HEARTBEAT_SECONDS=beat, STALE_RUN_REAPED_AFTER_SECONDS=ceiling)


@pytest.mark.parametrize("ceiling", [45.0, 120.0, 0.0, -1.0])
def test_three_beats_or_more_and_a_switched_off_sweep_are_accepted(ceiling: float) -> None:
    settings = Settings(RUN_HEARTBEAT_SECONDS=15.0, STALE_RUN_REAPED_AFTER_SECONDS=ceiling)
    assert ceiling == settings.STALE_RUN_REAPED_AFTER_SECONDS
