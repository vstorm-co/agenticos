"""A guard on the plugin that shuffles this suite.

`pytest-randomly` is the only thing standing between an order-dependent test and
a green build, and its absence is silent: without it the suite runs in collection
order, `-p no:randomly` becomes a no-op, and nothing anywhere says so. That is
not hypothetical. Both `docs/testing.md` and `.claude/rules/testing.md` described
it as on by default while it was in neither the dependency group nor the
lockfile, so the order-independence the docs called verified had never once been
exercised (#571).

The declaration is what makes the shuffle true for everybody who runs `uv sync`,
so that is what is asserted - deliberately not that the shuffle is active in this
process. Pinning collection order with `-p no:randomly` is the documented move
while bisecting an order-dependent failure, and a guard that turned it red would
be telling people to stop using it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_the_suite_is_shuffled_because_the_docs_say_it_is() -> None:
    config = tomllib.loads(PYPROJECT.read_text())
    dev_group: list[str] = config["dependency-groups"]["dev"]
    assert any(spec.startswith("pytest-randomly") for spec in dev_group), (
        "pytest-randomly is gone from the dev dependency group, so the suite now runs "
        "in collection order. Either put it back or correct docs/testing.md and "
        ".claude/rules/testing.md, which both promise a shuffled run and a live seed."
    )
