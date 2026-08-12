"""A guard on the plugin that shuffles this suite.

`pytest-randomly` is the only thing standing between an order-dependent test and
a green build, and its absence is silent: without it the suite runs in collection
order, `-p no:randomly` becomes a no-op, and nothing anywhere says so. That is
not hypothetical. Both `docs/testing.md` and `.claude/rules/testing.md` described
it as on by default while it was in neither the dependency group nor the
lockfile, so the order-independence the docs called verified had never once been
exercised (#571).

Two halves, because #571 was both: declared nowhere *and* installed nowhere. The
declaration is what makes the shuffle true for everybody who runs `uv sync`; the
import is what makes it true for the interpreter running this test, which a stale
virtualenv or a `pytest` invoked from outside `uv run` can disagree about.

Neither asserts that the shuffle is *active* in this process, deliberately.
Pinning collection order with `-p no:randomly` is the documented move while
bisecting an order-dependent failure - it deactivates the plugin without
uninstalling it, so both assertions below still hold - and a guard that turned it
red would be telling people to stop using it.
"""

from __future__ import annotations

import tomllib
from importlib.util import find_spec
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_the_dev_group_declares_the_plugin_that_shuffles_the_suite() -> None:
    with PYPROJECT.open("rb") as handle:
        config = tomllib.load(handle)
    dev_group: list[str] = config["dependency-groups"]["dev"]
    assert any(spec.startswith("pytest-randomly") for spec in dev_group), (
        "pytest-randomly is gone from the dev dependency group, so the suite now runs "
        "in collection order. Either put it back or correct docs/testing.md and "
        ".claude/rules/testing.md, which both promise a shuffled run and a live seed."
    )


def test_the_plugin_that_shuffles_the_suite_is_installed() -> None:
    assert find_spec("pytest_randomly") is not None, (
        "pytest-randomly is declared but not importable, so this run is in collection "
        "order whatever pyproject.toml says. Re-sync the environment with `uv sync`, "
        "and run the suite through `uv run` so it is the one that gets used."
    )
