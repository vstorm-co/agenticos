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

from app.agents.capabilities.coding_agent._task import SANDBOX_FAILURES
from app.schemas.coding_task_change import ChangedFile, ChangeSet, ChangeStatus
from app.services.sandbox_workspace import NOT_BROWSABLE, TOOLING_DIRS

logger = logging.getLogger(__name__)

CHANGES_ROOT = "/tmp/agenticos-changes"  # noqa: S108
"""Where each task's snapshot store is made - outside any workspace, so no file tool lists it."""

STORE_ENV = "AGENTICOS_CHANGES"
BASE_ENV = "AGENTICOS_CHANGES_BASE"

MAX_FILE_BYTES = 1024 * 1024
"""The largest file a snapshot reads when it is first seen; a larger one is in no diff.

A file indexed while smaller is still read after it grows past this - its
growth is the change - and one already larger when the task began is never
indexed, so its edit or removal is not either.
"""

MAX_PATCH_BYTES = 256 * 1024
"""How much of a task's patch is kept; past it, the files that follow have no hunks."""

MAX_FILES = 500
"""How many changed files are listed; past it, only how many more there were."""

MAX_LIST_BYTES = 1024 * 1024
"""How much of the file list is read back; a longer list is counted, not listed."""

SNAPSHOT_SECONDS = 120
"""How long one snapshot may take before the task goes ahead without a diff."""

TRUNCATED_MARKER = "\\ The patch was cut here: it is longer than the platform keeps.\n"
"""What ends a file's part of the patch where the ceiling cut it, in diff's own `\\` form."""

NO_GIT = 97
"""The exit code a snapshot answers with in a runtime that has no `git`."""

_PLATFORM_PATHS = tuple(f"./{prefix.rstrip('/')}" for prefix in NOT_BROWSABLE)
"""The platform's own writing - `.agenticos/`, skills, spilled tool output - kept out like the file browser keeps it out.

Not the task's work, and in a workspace several conversations share it is
somebody else's run: a spill written beside this task holds another person's
tool result, which a diff would otherwise store and show to this chat's readers.
"""

_PRUNED = " -o ".join(
    [f"-path {shlex.quote(path)}" for path in _PLATFORM_PATHS]
    + [f"-name {shlex.quote(name)}" for name in sorted(TOOLING_DIRS)]
)

_SETUP = (
    f"command -v git > /dev/null 2>&1 || exit {NO_GIT}; "
    f'export GIT_DIR="${STORE_ENV}/git" GIT_INDEX_FILE="${STORE_ENV}/index" '
    'GIT_WORK_TREE="$PWD" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null '
    "GIT_OPTIONAL_LOCKS=0; "
    # GNU find's `-readable`, where there is one: a file the sandbox user cannot
    # read would otherwise fail `update-index`, and with it every snapshot of
    # that workspace.
    "readable=; find . -maxdepth 0 -readable > /dev/null 2>&1 && readable=-readable; "
)

# `find`'s `-size -N` counts 512-byte blocks rounded up, so N is one past the ceiling's.
# `$readable` is unquoted on purpose: empty, it must be no argument at all.
_SNAPSHOT = (
    "{ git ls-files -z; "
    f"find . \\( {_PRUNED} \\) -prune -o \\( -type l -o -type f $readable \\) "
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
    f'{_DIFF} -z --raw --numstat > "${STORE_ENV}/list"; '
    f'{_DIFF} -p --no-color > "${STORE_ENV}/patch"; '
    f'wc -c < "${STORE_ENV}/list"; wc -c < "${STORE_ENV}/patch"; '
    # One `:`-led metadata line per file in the `--raw` half: how many there are, listed or not.
    f"{{ tr '\\000' '\\n' < \"${STORE_ENV}/list\" | grep -c '^:[0-7]* [0-7]* ' || true; }}; "
    f"head -c {MAX_LIST_BYTES} \"${STORE_ENV}/list\" | base64 | tr -d '\\n'; echo; "
    f'head -c {MAX_PATCH_BYTES} "${STORE_ENV}/patch"'
)
"""Snapshot again and print the change: the list's and the patch's sizes, the file count, the list (base64), the patch.

Both diffs are written to the store first, so `set -e` sees `diff-tree` fail -
piped straight out, a failing one printed nothing and read as a task that
changed nothing. The sizes are the bytes git wrote, before any decoding.
"""

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
        # Shielded: a run stopped here would otherwise cancel the removal too.
        with anyio.CancelScope(shield=True):
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
    list_size, _, rest = stdout.partition("\n")
    patch_size, _, rest = rest.partition("\n")
    total, _, rest = rest.partition("\n")
    encoded, _, patch = rest.partition("\n")
    if not all(size.strip().isdecimal() for size in (list_size, patch_size, total)):
        return None
    try:
        fields = base64.b64decode(encoded.strip(), validate=True)
    except binascii.Error, ValueError:
        return None
    if int(list_size) > MAX_LIST_BYTES:
        # Too many to list: counted, and the reader told so.
        return ChangeSet(omitted=int(total), truncated=True)
    entries = _entries(fields.decode("utf-8", errors="replace").split("\x00")[:-1])
    if entries is None:
        return None
    cut = int(patch_size) > MAX_PATCH_BYTES
    sections = _sections(patch.replace("\x00", ""), cut=cut)
    _attach(entries, sections, cut=cut)
    kept = [entry for entry, _ in entries[:MAX_FILES]]
    omitted = len(entries) - len(kept)
    hunkless = any(entry.patch is None for entry in kept)
    return ChangeSet(files=kept, omitted=omitted, truncated=omitted > 0 or hunkless)


def _entries(fields: list[str]) -> list[tuple[ChangedFile, int]] | None:
    """`--raw -z` then `--numstat -z`: each file in git's order, with how many parts of the patch it has.

    A type change - a file become a link - is one file and two parts.
    """
    files: list[tuple[ChangedFile, int]] = []
    position = 0
    while position < len(fields) and fields[position].startswith(":"):
        code = fields[position].rsplit(" ", 1)[-1][:1]
        renamed = code in ("R", "C")
        width = 3 if renamed else 2
        if position + width > len(fields):
            return None
        names = fields[position + 1 : position + width]
        entry = ChangedFile(
            path=names[-1],
            old_path=names[0] if renamed else None,
            status=_STATUS.get(code, "modified"),
        )
        files.append((entry, 2 if code == "T" else 1))
        position += width
    for entry, _ in files:
        if position >= len(fields):
            return None
        added, _, rest = fields[position].partition("\t")
        deleted, _, _ = rest.partition("\t")
        # A rename's counts end in an empty path, its two names in the next fields.
        position += 3 if entry.old_path is not None else 1
        entry.binary = added == "-"
        entry.additions = int(added) if added.isdecimal() else 0
        entry.deletions = int(deleted) if deleted.isdecimal() else 0
    return files


def _sections(patch: str, *, cut: bool) -> list[str]:
    """The patch split at each `diff --git` header, the part a cut left open dropped back to a line.

    Split on `\n` alone: `str.splitlines` also breaks at a form feed or a
    `\x1c`, which file content may hold, and content could then open a section
    of its own and move every later file's hunks under the wrong name.
    """
    if cut:
        patch = patch[: patch.rfind("\n") + 1]
    sections: list[str] = []
    for line in patch.split("\n")[:-1]:
        if line.startswith("diff --git ") or not sections:
            sections.append(f"{line}\n")
        else:
            sections[-1] += f"{line}\n"
    return sections


def _attach(files: list[tuple[ChangedFile, int]], sections: list[str], *, cut: bool) -> None:
    """Give each file its part of the patch, a type change taking two.

    The parts are git's own order, so they line up with the files - unless the
    count says otherwise, when no file is given parts that may be another's.
    """
    wanted = sum(parts for _, parts in files)
    if len(sections) > wanted or (not cut and len(sections) != wanted):
        logger.warning("A coding task's patch did not line up with its files; hunks left out")
        return
    position = 0
    for entry, parts in files:
        taken = sections[position : position + parts]
        position += parts
        if not taken:
            return
        entry.patch = "".join(taken)
        entry.truncated = cut and position >= len(sections)
        if entry.truncated:
            entry.patch += TRUNCATED_MARKER


def _is_object_id(text: str) -> bool:
    return len(text) in (40, 64) and all(char in "0123456789abcdef" for char in text)
