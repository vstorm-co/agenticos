"""A test that keeps every other Amigo a cut of the one drawing, not a second one.

Amigo is drawn once, in `docs/assets/amigo.svg`. The mark the site header, the
browser tab and the console's sidebar show is his head cut out of it, and the
walking sprite the README shows is the same drawing on a wider canvas with two
leg poses under it. `scripts/gen_amigo_assets.py` writes all three.

Derived files drift. Nothing about editing the mascot makes any of them change,
and the failure is invisible: they all still render, just an older face than the
one beside them. So this regenerates them in memory and compares.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATOR = REPO_ROOT / "scripts/gen_amigo_assets.py"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_amigo_assets", GENERATOR)
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


def test_the_walk_is_still_the_same_drawing(gen) -> None:
    assert gen.WALK_SVG.read_text() == gen.build_walk()


def test_the_walk_has_room_to_cross(gen) -> None:
    # The canvas is the sprite plus its stride; a viewBox that forgot the stride
    # is a sprite that walks out of its own frame halfway through the loop.
    assert f'viewBox="0 -1 {gen.WALK_W} 20"' in gen.build_walk()
    assert f"translateX({gen.STRIDE}px)" in gen.build_walk()


def test_the_walk_keeps_one_pair_of_legs_without_css(gen) -> None:
    # Where the CSS in an image does not run, the poses do not alternate - so the
    # one that is meant to be hidden carries an attribute rather than a rule, or
    # the fallback frame is a sprite with four legs and no eyes.
    walk = gen.build_walk()
    assert '<g class="amigo-step-b" opacity="0">' in walk
    assert walk.count('class="amigo-eyelid" opacity="0"') == 2
