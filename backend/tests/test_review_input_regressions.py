"""Public update inputs refuse ambiguous time and preserve explicit disable choices."""

import pytest
from pydantic import ValidationError

from app.schemas.memory import MemoryClaimCorrect
from app.schemas.watch import WatchUpdate


def test_a_claim_correction_rejects_a_timezone_less_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        MemoryClaimCorrect.model_validate(
            {"statement": "Corrected fact", "effective_from": "2026-12-01T00:00:00"}
        )
    correction = MemoryClaimCorrect.model_validate(
        {"statement": "Corrected fact", "effective_from": "2026-12-01T00:00:00+02:00"}
    )
    assert correction.effective_from is not None
    offset = correction.effective_from.utcoffset()
    assert offset is not None and offset.total_seconds() == 7200


def test_a_watch_failure_limit_can_be_explicitly_disabled() -> None:
    update = WatchUpdate.model_validate({"max_failures": None})
    assert update.model_dump(exclude_unset=True) == {"max_failures": None}
    with pytest.raises(ValidationError):
        WatchUpdate.model_validate({"title": None})
