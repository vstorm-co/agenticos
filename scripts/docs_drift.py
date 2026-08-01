#!/usr/bin/env python3
"""Report code changes whose documentation has not moved with them.

`docs/` is the single copy of how this system works, which only holds if the page
changes in the same commit as the behaviour. Nothing enforces that: a reviewer
reads a diff of code, the page keeps describing what the code used to do, and the
disagreement is discovered months later by somebody acting on the stale half.

So this compares the working tree against the trigger map below. If a path that a
page documents has changed and nothing under `docs/` has, it names the page.

It is a **reminder, not a gate**. There are legitimate reasons for the pair to be
uneven - a refactor that changes no behaviour, a test-only change - and a check
that blocked those would be routed around within a week. Exit is always 0.

Usage::

    python3 scripts/docs_drift.py            # human-readable, for a terminal
    python3 scripts/docs_drift.py --json     # {"systemMessage": ...} for a hook

Wired as a Stop hook in `.claude/settings.json`, so it runs when an agent finishes
a turn - the moment the change is fresh and the page is cheap to fix.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Path prefix -> the page that documents it. Ordered most specific first; the
# first match wins, so `app/agents/spec.py` reports the spec page rather than the
# capability catalog.
#
# Deliberately not exhaustive. A prefix belongs here when a page describes the
# *behaviour* of what lives there; adding all of `backend/app` would fire on every
# change and teach the reader to ignore it.
TRIGGERS: tuple[tuple[str, str], ...] = (
    ("backend/app/agents/spec.py", "docs/reference/spec.md"),
    ("backend/app/agents/capabilities/", "docs/reference/capabilities.md"),
    ("backend/app/agents/mcp", "docs/mcp.md"),
    ("backend/app/agents/model_resolver.py", "docs/models.md"),
    ("backend/app/services/mcp_", "docs/mcp.md"),
    ("backend/app/core/catalog/mcp_servers.json", "docs/mcp.md"),
    ("backend/app/services/model_profile.py", "docs/models.md"),
    ("backend/app/services/model_catalog.py", "docs/models.md"),
    ("backend/app/core/vault.py", "docs/secrets.md"),
    ("backend/app/core/secret_kinds.py", "docs/secrets.md"),
    ("backend/app/services/organization_secret.py", "docs/secrets.md"),
    ("backend/app/core/permissions.py", "docs/permissions.md"),
    ("backend/app/services/access.py", "docs/permissions.md"),
    ("backend/app/services/skills.py", "docs/skills.md"),
    ("backend/app/services/skill_library.py", "docs/skills.md"),
    ("backend/app/core/catalog/skills/", "docs/skills.md"),
    ("backend/app/services/spend.py", "docs/governance.md"),
    ("backend/app/services/approvals.py", "docs/governance.md"),
    ("backend/app/services/notifications.py", "docs/governance.md"),
    ("backend/app/services/channels/", "docs/channels.md"),
    ("backend/app/services/agent_exposure.py", "docs/channels.md"),
    ("backend/app/services/agent_embed.py", "docs/channels.md"),
    ("backend/app/services/rag/", "docs/file-processing.md"),
    ("backend/app/services/file_upload.py", "docs/file-processing.md"),
    ("backend/app/services/ingestion_config.py", "docs/file-processing.md"),
    ("backend/app/core/config.py", "docs/configuration.md"),
    ("backend/app/commands/", "docs/commands.md"),
    ("backend/app/api/routes/", "docs/architecture.md"),
    ("backend/alembic/versions/", "docs/architecture.md"),
    (".github/workflows/ai-review.yml", "docs/code-review.md"),
    (".github/codex/", "docs/code-review.md"),
)

# A change under any of these means the docs did move, so nothing is reported.
# `docs/plans/` is excluded: a plan file is a working note about an intended
# change, not a description of the system, so writing one is not documenting it.
DOC_ROOTS: tuple[str, ...] = ("docs/",)
DOC_EXCLUDED: tuple[str, ...] = ("docs/plans/", "docs/archive/")


def repo_root() -> Path | None:
    """The working tree this was run inside, or None if it is not a checkout."""
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(top) if top else None


def changed_paths(root: Path) -> list[str]:
    """Every path git reports as changed, staged or not, including untracked.

    Porcelain v1 so the format is stable. A rename arrives as `old -> new`; the
    destination is what matters, and it is what a trigger should match.
    """
    try:
        output = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    paths: list[str] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        entry = line[3:].strip().strip('"')
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1].strip().strip('"')
        paths.append(entry)
    return paths


def documented(paths: list[str]) -> bool:
    """Whether any change counts as documentation moving with the code."""
    return any(
        path.startswith(DOC_ROOTS) and not path.startswith(DOC_EXCLUDED)
        for path in paths
    )


def pages_owed(paths: list[str]) -> dict[str, list[str]]:
    """Page -> the changed paths that page describes."""
    owed: dict[str, list[str]] = {}
    for path in paths:
        for prefix, page in TRIGGERS:
            if path.startswith(prefix):
                owed.setdefault(page, []).append(path)
                break
    return owed


def report(owed: dict[str, list[str]]) -> str:
    """The reminder, naming each page and one path that earned it."""
    lines = [
        "Code changed but no docs page did. `docs/` is the single copy of how this "
        "works, so it only stays true if it moves in the same change:",
        "",
    ]
    for page in sorted(owed):
        paths = sorted(owed[page])
        first = paths[0]
        rest = f" (+{len(paths) - 1} more)" if len(paths) > 1 else ""
        lines.append(f"  {page}  <-  {first}{rest}")
    lines += [
        "",
        "If the change is a refactor with no behaviour change, or tests only, there is "
        "nothing to update - say so and move on.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help='emit {"systemMessage": ...} for a Claude Code hook',
    )
    args = parser.parse_args()

    root = repo_root()
    if root is None:
        return 0

    paths = changed_paths(root)
    if not paths or documented(paths):
        if not args.json:
            print(
                "No documentation drift: either nothing changed, or a page changed with it."
            )
        return 0

    owed = pages_owed(paths)
    if not owed:
        if not args.json:
            print("No documentation drift: nothing changed that a page describes.")
        return 0

    message = report(owed)
    if args.json:
        # `suppressOutput` keeps the raw stdout out of the transcript; the
        # systemMessage is the whole point and is surfaced on its own.
        print(json.dumps({"systemMessage": message, "suppressOutput": True}))
    else:
        print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
