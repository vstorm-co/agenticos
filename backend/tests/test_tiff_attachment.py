"""Converting a TIFF to the PNG pages the vision APIs will actually take.

TIFF is accepted for upload but no vision API draws it, so it is converted at the
point it is shown to the model. Multi-page scans contribute more than page one, up
to a cap, and the guards do not trust attacker-controlled pixel counts or walk the
whole IFD chain to bound the pages (#1591, §2.4/§7 finding 5).
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.file_upload import tiff_pages_to_png

pytestmark = pytest.mark.anyio

BIG = 10 * 1024 * 1024
MANY_PIXELS = 10**9


def _tiff(pages: int, *, size: tuple[int, int] = (16, 16)) -> bytes:
    frames = [Image.new("RGB", size, (i * 20 % 256, 0, 0)) for i in range(pages)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="TIFF", save_all=True, append_images=frames[1:])
    return buffer.getvalue()


class TestConvertingPages:
    def test_a_single_page_becomes_one_png(self):
        result = tiff_pages_to_png(_tiff(1), max_pages=10, max_bytes=BIG, max_pixels=MANY_PIXELS)

        assert len(result.images) == 1
        assert result.images[0].startswith(b"\x89PNG\r\n\x1a\n")
        assert result.total == 1
        assert result.omitted is False

    def test_every_page_under_the_cap_is_converted(self):
        result = tiff_pages_to_png(_tiff(3), max_pages=10, max_bytes=BIG, max_pixels=MANY_PIXELS)

        assert len(result.images) == 3
        assert result.total == 3
        assert result.omitted is False

    def test_pages_past_the_cap_are_omitted_with_an_unknown_total(self):
        """Stopped one past the cap rather than reading a total that walks the whole
        IFD chain, so the total is deliberately not asserted as known."""
        result = tiff_pages_to_png(_tiff(6), max_pages=2, max_bytes=BIG, max_pixels=MANY_PIXELS)

        assert len(result.images) == 2
        assert result.total is None
        assert result.omitted is True

    def test_a_page_over_the_pixel_bound_is_skipped_not_decoded(self):
        """The bomb guard: the declared size is checked before the pixels are
        decoded, so a huge page is skipped rather than allocated."""
        result = tiff_pages_to_png(_tiff(2), max_pages=10, max_bytes=BIG, max_pixels=4)

        assert result.images == []
        assert result.omitted is True

    def test_a_page_that_cannot_be_reduced_below_the_byte_cap_is_skipped(self):
        result = tiff_pages_to_png(_tiff(1), max_pages=10, max_bytes=1, max_pixels=MANY_PIXELS)

        assert result.images == []
        assert result.omitted is True

    def test_a_long_chain_of_rejected_frames_stops_at_the_page_cap(self):
        """The traversal is bounded by frames *examined*, not images produced: a
        run of oversized frames must not walk the whole IFD chain. `total is None`
        proves the loop broke at the cap rather than exhausting the sequence (which
        would set the total) — the old code counted only successful PNGs and walked
        every frame (#1591, §7 finding 2)."""
        result = tiff_pages_to_png(_tiff(20), max_pages=3, max_bytes=BIG, max_pixels=4)

        assert result.images == []
        assert result.omitted is True
        assert result.total is None

    def test_malformed_bytes_convert_to_nothing_without_raising(self):
        result = tiff_pages_to_png(
            b"not a tiff", max_pages=10, max_bytes=BIG, max_pixels=MANY_PIXELS
        )

        assert result.images == []
        assert result.total is None
        assert result.omitted is False
