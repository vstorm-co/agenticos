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

from app.services import file_upload
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
        result = tiff_pages_to_png(
            _tiff(1), max_pages=10, max_bytes=BIG, max_pixels=MANY_PIXELS, max_total_bytes=BIG
        )

        assert len(result.images) == 1
        assert result.images[0].startswith(b"\x89PNG\r\n\x1a\n")
        assert result.total == 1
        assert result.omitted is False

    def test_every_page_under_the_cap_is_converted(self):
        result = tiff_pages_to_png(
            _tiff(3), max_pages=10, max_bytes=BIG, max_pixels=MANY_PIXELS, max_total_bytes=BIG
        )

        assert len(result.images) == 3
        assert result.total == 3
        assert result.omitted is False

    def test_pages_past_the_cap_are_omitted_with_an_unknown_total(self):
        """Stopped one past the cap rather than reading a total that walks the whole
        IFD chain, so the total is deliberately not asserted as known."""
        result = tiff_pages_to_png(
            _tiff(6), max_pages=2, max_bytes=BIG, max_pixels=MANY_PIXELS, max_total_bytes=BIG
        )

        assert len(result.images) == 2
        assert result.total is None
        assert result.omitted is True

    def test_a_tiff_at_exactly_the_cap_is_not_reported_as_omitted(self):
        """A TIFF with exactly `max_pages` frames is exhausted, not truncated: the
        cap is checked one frame *past* the last, so the loop does not claim pages
        were omitted without a frame beyond the cap to prove it - which, at
        `CHAT_TIFF_MAX_INLINE_PAGES=1`, was every ordinary one-page TIFF (#1591)."""
        result = tiff_pages_to_png(
            _tiff(2), max_pages=2, max_bytes=BIG, max_pixels=MANY_PIXELS, max_total_bytes=BIG
        )

        assert len(result.images) == 2
        assert result.total == 2
        assert result.omitted is False

    def test_a_single_page_at_a_cap_of_one_is_not_omitted(self):
        result = tiff_pages_to_png(
            _tiff(1), max_pages=1, max_bytes=BIG, max_pixels=MANY_PIXELS, max_total_bytes=BIG
        )

        assert len(result.images) == 1
        assert result.total == 1
        assert result.omitted is False

    def test_a_page_over_the_pixel_bound_is_skipped_not_decoded(self):
        """The bomb guard: the declared size is checked before the pixels are
        decoded, so a huge page is skipped rather than allocated."""
        result = tiff_pages_to_png(
            _tiff(2), max_pages=10, max_bytes=BIG, max_pixels=4, max_total_bytes=BIG
        )

        assert result.images == []
        assert result.omitted is True

    def test_a_page_that_cannot_be_reduced_below_the_byte_cap_is_skipped(self):
        result = tiff_pages_to_png(
            _tiff(1), max_pages=10, max_bytes=1, max_pixels=MANY_PIXELS, max_total_bytes=BIG
        )

        assert result.images == []
        assert result.omitted is True

    def test_a_long_chain_of_rejected_frames_stops_at_the_page_cap(self):
        """The traversal is bounded by frames *examined*, not images produced: a
        run of oversized frames must not walk the whole IFD chain. `total is None`
        proves the loop broke at the cap rather than exhausting the sequence (which
        would set the total) — the old code counted only successful PNGs and walked
        every frame (#1591, §7 finding 2)."""
        result = tiff_pages_to_png(
            _tiff(20), max_pages=3, max_bytes=BIG, max_pixels=4, max_total_bytes=BIG
        )

        assert result.images == []
        assert result.omitted is True
        assert result.total is None

    def test_malformed_bytes_convert_to_nothing_without_raising(self):
        result = tiff_pages_to_png(
            b"not a tiff", max_pages=10, max_bytes=BIG, max_pixels=MANY_PIXELS, max_total_bytes=BIG
        )

        assert result.images == []
        assert result.total is None
        assert result.omitted is False

    def test_a_broken_later_frame_keeps_the_pages_already_converted(self, monkeypatch):
        """A decode failure partway down the chain must not discard the pages that
        already converted: page one survives and the rest are marked omitted rather
        than the whole TIFF reported unshowable (#1591, third-pass finding 4)."""
        real = file_upload._frame_to_png
        calls = {"n": 0}

        def flaky(frame, *, max_bytes, max_pixels):
            calls["n"] += 1
            if calls["n"] == 1:
                return real(frame, max_bytes=max_bytes, max_pixels=max_pixels)
            raise ValueError("unsupported compression")

        monkeypatch.setattr(file_upload, "_frame_to_png", flaky)
        result = tiff_pages_to_png(
            _tiff(3), max_pages=10, max_bytes=BIG, max_pixels=MANY_PIXELS, max_total_bytes=BIG
        )

        assert len(result.images) == 1
        assert result.images[0].startswith(b"\x89PNG\r\n\x1a\n")
        assert result.omitted is True

    def test_a_frame_walk_that_raises_mid_sequence_keeps_earlier_pages(self, monkeypatch):
        """When advancing the IFD chain itself raises after a page converted, the
        converted page is preserved and the rest marked omitted."""
        from PIL import ImageSequence

        real_iterator = ImageSequence.Iterator

        class FlakyIterator:
            def __init__(self, img):
                self._inner = real_iterator(img)
                self._n = 0

            def __iter__(self):
                return self

            def __next__(self):
                self._n += 1
                if self._n == 2:
                    raise OSError("broken strip offset")
                return next(self._inner)

        # The function does `from PIL import ImageSequence`, so patching the PIL
        # module's attribute is what the local import binds at call time.
        monkeypatch.setattr(ImageSequence, "Iterator", FlakyIterator)
        result = tiff_pages_to_png(
            _tiff(3), max_pages=10, max_bytes=BIG, max_pixels=MANY_PIXELS, max_total_bytes=BIG
        )

        assert len(result.images) == 1
        assert result.total is None
        assert result.omitted is True
