"""A test that keeps the product mark a crop of the mascot, and not a second drawing.

Amigo is drawn once, in `docs/assets/amigo.svg`. The mark the site header, the
browser tab and the console's sidebar show is his head cut out of that drawing by
`scripts/gen_amigo_head.py`, which writes two derived files - an SVG for MkDocs and
a data URI for `next/og`, which cannot load a path.

Derived files drift. Nothing about editing the mascot makes either of them change,
and the failure is invisible: both still render, just an older face than the one in
the README. So this regenerates them in memory and compares.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATOR = REPO_ROOT / "scripts/gen_amigo_head.py"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_amigo_head", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _generator()


def test_the_derived_mark_still_matches_the_mascot(gen) -> None:
    assert gen.MARK_SVG.read_text() == gen.build_mark()


def test_the_consoles_data_uri_still_matches_the_mascot(gen) -> None:
    assert gen.MARK_TS.read_text() == gen.build_module(gen.build_mark())


def test_the_mark_is_square_so_it_fits_an_icon_slot(gen) -> None:
    # A non-square mark is letterboxed in every square slot it lands in, which is
    # the whole reason the head is cropped out of a 16-by-20 character.
    assert 'viewBox="0 0 16 16"' in gen.build_mark()


def test_the_blink_frames_are_left_out_of_the_crop(gen) -> None:
    # The mascot's eyelids are animation, not drawing: they sit over the eyes at
    # zero opacity and are the one pair of pixels the crop must not bake in.
    assert "amigo-eyelid" in gen.MASCOT.read_text()
    assert "amigo-eyelid" not in gen.build_mark()
