#!/usr/bin/env python3
"""Which expensive CI jobs a pull request's changed paths cannot possibly affect.

`test`, `test-frontend` and `e2e` are 8.2, 5.3 and 5.1 billed minutes of every CI
run, and a backend-only pull request pays all three. This decides which of them
may be skipped - and it is deliberately written the timid way round.

**A job is skipped only when every changed path is provably irrelevant to it.**
Not "run it when a path I recognise as relevant changed", which is the same
sentence with the failure mode reversed: an unclassified path - a new top-level
directory, a config file nobody thought about - would silently stop a suite from
running, and a suite that does not run is a gate that reads green because the
thing is not in it. That is #143 and #165, and it is the mistake this file exists
to not make. So anything unrecognised runs everything.

Which is why the exemptions are only these, each true because it was checked:

`docs/**`, `mkdocs.yml` and a top-level `*.md`
:   No test under `backend/tests/` reads any of them - the one mention is a
    docstring naming `docs/channels.md` in prose. The `docs` job builds the site
    on every run and is not gated here, so a dead link still fails the build.

`frontend/**` for the backend suite, `backend/**` for the frontend suite
:   The two halves share no source. They do share the *pull request*, which is
    why `e2e` is exempted from neither.

Everything else runs everything, `.github/**` and `Makefile` emphatically
included: `tests/test_ci_parity.py` reads both, so a workflow edit is a change
the backend suite has an opinion about - this very file's arrival among them.

**A rename is two paths, and the caller owes both.** The proof this makes is over
every path a change touched, and GitHub's `pulls/{n}/files` reports only the *new*
one in `filename` - so a module renamed out of `backend/` into `frontend/` would
arrive as a single frontend path and skip the backend suite for a change that
deleted a backend module. The `changes` job therefore feeds `previous_filename`
through as well; `tests/test_ci_changed_scope.py` asserts that it still does,
because nothing here can detect its absence.

Usage, from the `changes` job:

    python3 scripts/ci_changed_scope.py changed-files.txt >> "$GITHUB_OUTPUT"
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

# The jobs this decides for, in the order the workflow declares them.
JOBS = ("backend", "frontend", "e2e")


def _is_documentation(path: str) -> bool:
    """A path that no test reads and only the `docs` job builds."""
    if path.startswith("docs/") or path == "mkdocs.yml":
        return True
    return "/" not in path and path.endswith(".md")


def _irrelevant_to(job: str, path: str) -> bool:
    if _is_documentation(path):
        return True
    if job == "backend":
        return path.startswith("frontend/")
    if job == "frontend":
        return path.startswith("backend/")
    # `e2e` drives the frontend against the backend, so either half affects it.
    return False


def scope(paths: Iterable[str]) -> dict[str, bool]:
    """Map each job to whether this change set requires it to run.

    An empty change set runs everything. That is not a case worth optimising -
    a pull request with no files is a pull request with nothing to skip for -
    and `all()` over nothing answering `True` would skip all three.
    """
    changed = [path for path in paths if path]
    if not changed:
        return dict.fromkeys(JOBS, True)
    return {job: not all(_irrelevant_to(job, path) for path in changed) for job in JOBS}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <file-of-changed-paths>", file=sys.stderr)
        return 2

    paths = Path(argv[1]).read_text().splitlines()
    decided = scope(paths)
    for job, required in decided.items():
        print(f"{job}={'true' if required else 'false'}")

    skipped = sorted(job for job, required in decided.items() if not required)
    # Counted the way `scope` counts, so the number names what was decided on rather
    # than how many lines the file happened to have.
    counted = sum(1 for path in paths if path)
    print(
        f"{counted} changed path(s); skipping {', '.join(skipped) if skipped else 'nothing'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
