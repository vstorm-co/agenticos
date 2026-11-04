"""What a coding task changed in the sandbox: a snapshot before it, a diff after it (#2480).

The harness reports the files it touched, in its own words, and leaves out what a
command it ran wrote. A person deciding whether to keep the work wants the work
itself. So the workspace is snapshotted before the task and again after it, and
the change set is the difference between the two.

The snapshot is a git tree written into a store of the task's own, outside the
workspace (`CHANGES_ROOT`), with its own index - never the repository a person
cloned into the workspace, whose index, stash and history stay untouched, and not
`git add`, which stops at a nested repository and records only its commit. Every
file is listed with `find` instead, so a clone inside the workspace is diffed
file by file and a workspace that is no repository at all is diffed the same way.
The second snapshot reuses the first one's index, so only files whose size or
time changed are read again. The store is removed once the diff is read.

Left out, and so never in a diff: `.agenticos/` (the task's own files), the
folders a toolchain fills (`TOOLING_DIRS`, `.git` among them), and any file past
`MAX_FILE_BYTES`. A task running beside another in a shared sandbox sees that
one's edits in its diff as well: the snapshot is of the workspace, not of one
process's writes.
"""

import base64
import binascii
import logging
import shlex
import uuid
from dataclasses import dataclass
from typing import Any

import anyio
from pydantic_ai.tools import RunContext

from app.agents.capabilities.coding_agent._task import SANDBOX_FAILURES, WORK_DIR
from app.schemas.coding_change import ChangedFile, ChangeSet, ChangeStatus
from app.services.sandbox_workspace import TOOLING_DIRS

logger = logging.getLogger(__name__)

CHANGES_ROOT = "/tmp/agenticos-changes"  # noqa: S108
"""Where each task's snapshot store is made - outside any workspace, so no file tool lists it."""

STORE_ENV = "AGENTICOS_CHANGES"
BASE_ENV = "AGENTICOS_CHANGES_BASE"

MAX_FILE_BYTES = 1024 * 1024
"""The largest file a snapshot reads; a larger one is in no diff."""

MAX_PATCH_BYTES = 256 * 1024
"""How much of a task's patch is kept; past it, the files that follow have no hunks."""

MAX_FILES = 500
"""How many changed files are listed; past it, only how many more there were."""

SNAPSHOT_SECONDS = 120
"""How long one snapshot may take before the task goes ahead without a diff."""

TRUNCATED_MARKER = "\n\\ The patch was cut here: it is longer than the platform keeps.\n"
"""What ends a file's part of the patch where the ceiling cut it, in diff's own `\\` form."""

NO_GIT = 97
"""The exit code a snapshot answers with in a runtime that has no `git`."""

_PRUNED = " -o ".join(
    ["-path ./" + WORK_DIR.split("/", 1)[0]]
    + [f"-name {shlex.quote(name)}" for name in sorted(TOOLING_DIRS)]
)

_SETUP = (
    f"command -v git > /dev/null 2>&1 || exit {NO_GIT}; "
    f'export GIT_DIR="${STORE_ENV}/git" GIT_INDEX_FILE="${STORE_ENV}/index" '
    'GIT_WORK_TREE="$PWD" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null '
    "GIT_OPTIONAL_LOCKS=0; "
)

# `find`'s `-size -N` counts 512-byte blocks rounded up, so N is one past the ceiling's.
_SNAPSHOT = (
    "{ git ls-files -z; "
    f"find . \\( {_PRUNED} \\) -prune -o \\( -type f -o -type l \\) "
    f"-size -{MAX_FILE_BYTES // 512 + 1} -print0; }} "
    "| git -c core.looseCompression=1 update-index -z --add --remove --stdin "
    "&& git write-tree"
)

BEGIN = f'{_SETUP}set -e; umask 077; rm -rf "${STORE_ENV}"; mkdir -p "${STORE_ENV}"; git init -q; {_SNAPSHOT}'
"""Make the task's store and snapshot the workspace into it; prints the tree."""

_DIFF = (
    f'git -c core.quotepath=off diff-tree -r -M --no-ext-diff --no-textconv "${BASE_ENV}" "$after"'
)

FINISH = (
    f"{_SETUP}set -e; after=$({_SNAPSHOT}); "
    f"{_DIFF} -z --name-status | base64 | tr -d '\\n'; echo; "
    f"{_DIFF} -z --numstat | base64 | tr -d '\\n'; echo; "
    f"{_DIFF} -p --no-color | head -c {MAX_PATCH_BYTES + 1}"
)
"""Snapshot again and print the change: name-status and numstat (base64), then the patch."""

DISCARD = f'rm -rf "${STORE_ENV}"'

_STATUS: dict[str, ChangeStatus] = {"A": "added", "D": "deleted", "R": "renamed"}


@dataclass(frozen=True)
class Baseline:
    """The task's snapshot store, and the tree the workspace was before the task."""

    store: str
    tree: str


async def begin(ctx: RunContext[Any]) -> Baseline | None:
    """Snapshot the workspace before a task; `None` when it cannot be, and the task runs anyway.

    A runtime without `git`, a workspace too large to snapshot in
    `SNAPSHOT_SECONDS` or a sandbox that refused the command costs the person the
    diff, never the task - and is logged, so a deployment missing every diff can
    find out why.
    """
    store = f"{CHANGES_ROOT}/{uuid.uuid4().hex}"
    try:
        result = await ctx.workspace.run(  # noqa: S604
            BEGIN, shell=True, env={STORE_ENV: store}, timeout=SNAPSHOT_SECONDS
        )
    except SANDBOX_FAILURES as failed:
        logger.warning("A coding task's workspace could not be snapshotted: %r", failed)
        await discard(ctx, store)
        return None
    except BaseException:
        # Stopped while snapshotting: the store would otherwise stay in `/tmp`.
        with anyio.CancelScope(shield=True):
            await discard(ctx, store)
        raise
    tree = result.stdout.strip().rsplit("\n", 1)[-1].strip()
    if result.exit_code != 0 or not _is_object_id(tree):
        if result.exit_code != NO_GIT:
            logger.warning(
                "A coding task's workspace could not be snapshotted (exit %s): %s",
                result.exit_code,
                result.stderr.strip()[-500:],
            )
        await discard(ctx, store)
        return None
    return Baseline(store=store, tree=tree)


async def finish(ctx: RunContext[Any], baseline: Baseline) -> ChangeSet | None:
    """What changed since `baseline`; `None` when the second snapshot failed. The store goes either way."""
    try:
        result = await ctx.workspace.run(  # noqa: S604
            FINISH,
            shell=True,
            env={STORE_ENV: baseline.store, BASE_ENV: baseline.tree},
            timeout=SNAPSHOT_SECONDS,
        )
    except SANDBOX_FAILURES as failed:
        logger.warning("A coding task's changes could not be read: %r", failed)
        return None
    finally:
        await discard(ctx, baseline.store)
    if result.exit_code != 0:
        logger.warning(
            "A coding task's changes could not be read (exit %s): %s",
            result.exit_code,
            result.stderr.strip()[-500:],
        )
        return None
    return parse(result.stdout)


async def discard(ctx: RunContext[Any], store: str) -> None:
    try:
        await ctx.workspace.run(  # noqa: S604
            DISCARD, shell=True, env={STORE_ENV: store}, timeout=60
        )
    except SANDBOX_FAILURES as failed:
        # A store left in `/tmp` goes with the container; nothing reads it again.
        logger.warning("A coding task's snapshot store %s was not removed: %r", store, failed)


def parse(stdout: str) -> ChangeSet | None:
    """The change set `FINISH` printed, or `None` for output that is not one."""
    statuses_line, _, rest = stdout.partition("\n")
    counts_line, _, patch = rest.partition("\n")
    try:
        statuses = _fields(statuses_line)
        counts = _fields(counts_line)
    except binascii.Error, ValueError:
        return None
    files = _entries(statuses, counts)
    if files is None:
        return None
    sections, cut = _sections(patch.replace("\x00", ""))
    kept = files[:MAX_FILES]
    for index, entry in enumerate(kept):
        if index < len(sections):
            entry.patch = sections[index]
            entry.truncated = cut and index == len(sections) - 1
            if entry.truncated:
                entry.patch += TRUNCATED_MARKER
    omitted = len(files) - len(kept)
    hunkless = any(entry.patch is None for entry in kept)
    return ChangeSet(files=kept, omitted=omitted, truncated=cut or omitted > 0 or hunkless)


def _fields(line: str) -> list[str]:
    raw = base64.b64decode(line.strip(), validate=True).decode("utf-8", errors="replace")
    return raw.split("\x00")[:-1] if raw else []


def _entries(statuses: list[str], counts: list[str]) -> list[ChangedFile] | None:
    """`--name-status -z` and `--numstat -z`, one entry per file, in git's order."""
    files: list[ChangedFile] = []
    position = 0
    while position < len(statuses):
        code = statuses[position][:1]
        renamed = code in ("R", "C")
        width = 3 if renamed else 2
        if position + width > len(statuses):
            return None
        names = statuses[position + 1 : position + width]
        files.append(
            ChangedFile(
                path=names[-1],
                old_path=names[0] if renamed else None,
                status=_STATUS.get(code, "modified"),
            )
        )
        position += width
    position = 0
    for entry in files:
        if position >= len(counts):
            return None
        added, _, rest = counts[position].partition("\t")
        deleted, _, _ = rest.partition("\t")
        # A rename's counts end in an empty path, its two names in the next fields.
        position += 3 if entry.old_path is not None else 1
        entry.binary = added == "-"
        entry.additions = int(added) if added.isdigit() else 0
        entry.deletions = int(deleted) if deleted.isdigit() else 0
    return files


def _sections(patch: str) -> tuple[list[str], bool]:
    """The patch split at each file's `diff --git` header, and whether it was cut short."""
    cut = len(patch.encode()) > MAX_PATCH_BYTES
    if cut:
        kept = patch.encode()[:MAX_PATCH_BYTES].decode("utf-8", errors="ignore")
        patch = kept[: kept.rfind("\n") + 1]
    sections: list[str] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git ") or not sections:
            sections.append(line)
        else:
            sections[-1] += line
    return sections, cut


def _is_object_id(text: str) -> bool:
    return len(text) in (40, 64) and all(char in "0123456789abcdef" for char in text)
