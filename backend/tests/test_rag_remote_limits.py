"""Partial failed responses remain charged to the source's transfer budget."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.exceptions import BadRequestError
from app.services.rag import remote_limits
from app.services.rag.remote_limits import DownloadBudget, write_download

pytestmark = pytest.mark.security


def test_failed_transfers_cannot_reset_the_sync_byte_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(remote_limits, "MAX_SYNC_BYTES", 5)
    budget = DownloadBudget()
    path = tmp_path / "document.pdf"

    def broken_response() -> Iterator[bytes]:
        yield b"abc"
        raise OSError("connection lost")

    with pytest.raises(OSError):
        write_download(path, broken_response(), budget.allowance(None))
    assert not path.exists()
    assert budget.used_bytes == 3

    with pytest.raises(BadRequestError):
        write_download(path, [b"abc"], budget.allowance(None))
    assert not path.exists()
    with pytest.raises(BadRequestError):
        budget.allowance(None)


def test_a_listing_stops_before_returning_data_after_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = remote_limits.ListingBudget(started_at=0)
    monkeypatch.setattr(
        remote_limits.time, "monotonic", lambda: remote_limits.MAX_LISTING_SECONDS + 1
    )
    with pytest.raises(BadRequestError):
        budget.observe(1, downloadable=True)
    assert budget.items == 0
