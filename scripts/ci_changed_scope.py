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
    why `e2e` is exempted from neither - and they share one directory, which is
    why the backend exemption stops short of `frontend/src/app/api/**`. Those
    are the BFF proxies, and `tests/api/test_bff_forwarded_paths.py` checks the
    paths they hard-code against the backend's own route table. A guard that
    skipped on the change it guards is the gate reading green because the thing
    is not in it, which is the mistake above.

`backend/pyproject.toml`, `backend/uv.lock` and `frontend/package.json` **when the
only thing their diff changes is the version string**
:   The one exemption here that reads a diff rather than a path, and the only one
    that could be: those three files carry the version *and* the dependency lists,
    the coverage `include` lists and the ruff and ty configuration, so the path
    alone proves nothing. A `chore: cut 0.0.x` is three version strings and a
    CHANGELOG entry - which is already exempt, being a top-level `*.md` - and it
    ran the whole 18-minute matrix against a change no suite can observe. #317
    claimed a release would stop paying for it; it did not, and this is what
    that claim needs to be true.

    Timid in the same direction as everything else: a patch that is absent,
    unreadable, or holds one line this does not recognise runs everything. It is
    keyed on the diff rather than on the branch name or the commit subject
    precisely because those are a claim anybody can make - a gate you pass by
    naming your branch `chore/cut-` is the gate reading green because the thing is
    not in it.

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

    python3 scripts/ci_changed_scope.py changed-files.txt [patches.json] >> "$GITHUB_OUTPUT"
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

# The jobs this decides for, in the order the workflow declares them.
JOBS = ("backend", "frontend", "e2e")

VERSIONED = ("backend/pyproject.toml", "backend/uv.lock", "frontend/package.json")
"""The three files a release cut edits besides the CHANGELOG."""

_VERSION_LINE = re.compile(r'^\s*(?:version\s*=|"version":)\s*"\d+\.\d+\.\d+"\s*,?\s*$')
"""One version assignment, in either the TOML or the JSON spelling.

Anchored end to end on purpose. A dependency pinned to a version in the same file
is `name = "fastapi"` on its own line, so it does not match; a line that both
sets the version and does something else does not match either.
"""


def _is_documentation(path: str) -> bool:
    """A path that no test reads and only the `docs` job builds."""
    if path.startswith("docs/") or path == "mkdocs.yml":
        return True
    return "/" not in path and path.endswith(".md")


def _is_version_only(patch: str | None) -> bool:
    """Whether this file's diff changes the version string and nothing else.

    `None` - the caller passed no patches, or GitHub omitted one, which it does
    for a file too large to inline - is not a proof, so it is `False`.

    A rewrite counts every changed line: a diff that raises the version *and*
    adds a dependency has one line this does not recognise, and one is enough.
    """
    if not patch:
        return False
    changed = [
        line
        for line in patch.splitlines()
        if line[:1] in {"+", "-"} and not line.startswith(("+++", "---"))
    ]
    if not changed:
        return False
    return all(_VERSION_LINE.match(line[1:]) for line in changed)


def _irrelevant_to(job: str, path: str, patches: Mapping[str, str]) -> bool:
    if _is_documentation(path):
        return True
    if path in VERSIONED and _is_version_only(patches.get(path)):
        return True
    if job == "backend":
        # The BFF proxies are the exception: the backend suite reads them.
        return path.startswith("frontend/") and not path.startswith("frontend/src/app/api/")
    if job == "frontend":
        return path.startswith("backend/")
    # `e2e` drives the frontend against the backend, so either half affects it.
    return False


def scope(paths: Iterable[str], patches: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Map each job to whether this change set requires it to run.

    An empty change set runs everything. That is not a case worth optimising -
    a pull request with no files is a pull request with nothing to skip for -
    and `all()` over nothing answering `True` would skip all three.
    """
    changed = [path for path in paths if path]
    if not changed:
        return dict.fromkeys(JOBS, True)
    seen = patches or {}
    return {job: not all(_irrelevant_to(job, path, seen) for path in changed) for job in JOBS}


def _patches_from(path: Path) -> dict[str, str]:
    """The `filename` → `patch` map from what `pulls/{n}/files` answered.

    Unreadable or malformed answers with an empty map rather than raising, which
    is the timid direction: no patch is no proof, and every version file then
    runs everything.
    """
    try:
        listed = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(listed, list):
        return {}
    return {
        entry["filename"]: entry["patch"]
        for entry in listed
        if isinstance(entry, dict) and isinstance(entry.get("patch"), str)
    }


def main(argv: list[str]) -> int:
    if len(argv) not in {2, 3}:
        print(f"usage: {argv[0]} <file-of-changed-paths> [file-of-patches]", file=sys.stderr)
        return 2

    paths = Path(argv[1]).read_text().splitlines()
    patches = _patches_from(Path(argv[2])) if len(argv) == 3 else {}
    decided = scope(paths, patches)
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
