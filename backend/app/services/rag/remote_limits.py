"""Resource ceilings shared by remote knowledge-base sync readers."""

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import BadRequestError

MIB = 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
# Provider pagination limits response size, not total work. These ceilings bound
# one source independently of provider defaults and the worker's outer timeout.
MAX_SYNC_ITEMS = 10_000
MAX_SYNC_PAGES = 1_000
MAX_SYNC_BYTES = 1024 * MIB
MAX_LISTING_SECONDS = 15 * 60


def _file_limit_bytes() -> int:
    return settings.MAX_UPLOAD_SIZE_MB * MIB


def _invalid_size(size: int) -> BadRequestError:
    return BadRequestError(
        message="A remote source reported an invalid file size.",
        details={"size_bytes": size},
    )


def _file_too_large(size: int | None = None) -> BadRequestError:
    limit = _file_limit_bytes()
    details = {"limit_bytes": limit}
    if size is not None:
        details["size_bytes"] = size
    return BadRequestError(
        message=f"A synced file is larger than the {settings.MAX_UPLOAD_SIZE_MB} MB limit.",
        details=details,
    )


def _sync_too_large(size: int | None = None) -> BadRequestError:
    details = {"limit_bytes": MAX_SYNC_BYTES}
    if size is not None:
        details["size_bytes"] = size
    return BadRequestError(
        message=(
            f"The remote source exceeds the {MAX_SYNC_BYTES // MIB} MB one sync may download. "
            "Narrow the configured folder or prefix."
        ),
        details=details,
    )


@dataclass
class ListingBudget:
    """Bound provider entries, elapsed listing time, and declared downloadable bytes."""

    items: int = 0
    pages: int = 0
    declared_bytes: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def check_time(self) -> None:
        if time.monotonic() - self.started_at > MAX_LISTING_SECONDS:
            raise BadRequestError(
                message=(
                    f"The remote source listing exceeded its {MAX_LISTING_SECONDS // 60}-minute "
                    "limit. Narrow the configured folder or prefix."
                ),
                details={"limit_seconds": MAX_LISTING_SECONDS},
            )

    def observe(self, size: int | None, *, downloadable: bool) -> None:
        """Account for one provider entry before retaining or traversing it."""
        self.check_time()
        self.items += 1
        if self.items > MAX_SYNC_ITEMS:
            raise BadRequestError(
                message=(
                    f"The remote source lists more than the {MAX_SYNC_ITEMS} entries one sync may "
                    "inspect. Narrow the configured folder or prefix."
                ),
                details={"limit_items": MAX_SYNC_ITEMS},
            )
        if size is None or not downloadable:
            return
        if size < 0:
            raise _invalid_size(size)
        # Oversized files are refused individually before fetch, so they are not
        # work this sync may download and do not consume its aggregate byte budget.
        if size <= _file_limit_bytes():
            self.declared_bytes += size
            if self.declared_bytes > MAX_SYNC_BYTES:
                raise _sync_too_large(self.declared_bytes)

    def observe_page(self) -> None:
        """Account for a provider response even when it contains no entries."""
        self.check_time()
        self.pages += 1
        if self.pages > MAX_SYNC_PAGES:
            raise BadRequestError(
                message=(
                    f"The remote source listing exceeds the {MAX_SYNC_PAGES} pages one sync may "
                    "inspect. Narrow the configured folder or prefix."
                ),
                details={"limit_pages": MAX_SYNC_PAGES},
            )


@dataclass
class DownloadAllowance:
    """The bytes one download may still write and which ceiling supplied them."""

    max_bytes: int
    sync_limited: bool
    budget: DownloadBudget | None = field(default=None, repr=False)
    charged_bytes: int = 0

    def refusal(self, size: int | None = None) -> BadRequestError:
        return _sync_too_large(size) if self.sync_limited else _file_too_large(size)

    def check_declared(self, size: int | None) -> None:
        if size is None:
            return
        if size < 0:
            raise _invalid_size(size)
        if size > self.max_bytes:
            raise self.refusal(size)

    def consume(self, size: int) -> None:
        """Charge bytes already received before deciding whether they may be written."""
        self.charged_bytes += size
        if self.budget is not None:
            self.budget.used_bytes += size
            if self.budget.used_bytes > MAX_SYNC_BYTES:
                raise _sync_too_large(self.budget.used_bytes)
        if self.charged_bytes > self.max_bytes:
            raise self.refusal(self.charged_bytes)


@dataclass
class DownloadBudget:
    """Track actual bytes downloaded by one connector instance and sync run."""

    used_bytes: int = 0

    def allowance(self, declared_size: int | None) -> DownloadAllowance:
        if declared_size is not None and declared_size < 0:
            raise _invalid_size(declared_size)
        file_limit = _file_limit_bytes()
        if declared_size is not None and declared_size > file_limit:
            raise _file_too_large(declared_size)
        remaining = MAX_SYNC_BYTES - self.used_bytes
        if remaining <= 0:
            raise _sync_too_large(self.used_bytes)
        if declared_size is not None and declared_size > remaining:
            raise _sync_too_large(self.used_bytes + declared_size)
        return DownloadAllowance(
            max_bytes=min(file_limit, remaining),
            sync_limited=remaining < file_limit,
            budget=self,
        )

    def record(self, path: Path, allowance: DownloadAllowance) -> None:
        size = path.stat().st_size
        if size > allowance.max_bytes:
            path.unlink(missing_ok=True)
            raise allowance.refusal(size)
        # Streamed readers charge chunks as they arrive, including bytes from a
        # failed partial response. Non-streaming sibling connectors are charged
        # here from the completed file instead.
        uncharged = max(0, size - allowance.charged_bytes)
        if self.used_bytes + uncharged > MAX_SYNC_BYTES:
            path.unlink(missing_ok=True)
            raise _sync_too_large(self.used_bytes + uncharged)
        self.used_bytes += uncharged


def write_download(path: Path, chunks: Iterable[bytes], allowance: DownloadAllowance) -> None:
    """Write streamed chunks under an allowance and remove every partial result."""
    try:
        with path.open("wb") as handle:
            for chunk in chunks:
                if not chunk:
                    continue
                allowance.consume(len(chunk))
                handle.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
