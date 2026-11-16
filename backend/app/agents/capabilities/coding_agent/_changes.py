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
`MAX_FILE_BYTES`. Coding tasks within one toolset queue around their snapshots and execution.
Other writers in a shared sandbox can still appear in the diff: a snapshot
records the workspace, not one process's writes.
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
from app.schemas.coding_task_change import (
    MAX_REVERT_BYTES,
    MAX_REVERT_FILE_BYTES,
    ChangedFile,
    ChangeSet,
    ChangeStatus,
)
from app.services.sandbox_workspace import NOT_BROWSABLE, TOOLING_DIRS

logger = logging.getLogger(__name__)

CHANGES_ROOT = "/tmp/agenticos-changes"  # noqa: S108
"""Where each task's snapshot store is made - outside any workspace, so no file tool lists it."""

STORE_ENV = "AGENTICOS_CHANGES"
BASE_ENV = "AGENTICOS_CHANGES_BASE"

MAX_FILE_BYTES = 1024 * 1024
"""The largest file a snapshot reads when it is first seen; a larger one is in no diff.

A file indexed while smaller is still read after it grows past this - its
growth is the change. One already larger when the task began is never
indexed, so its edit or removal is in no diff, and neither is one the task
creates larger; one the task shrinks below it reads as added.
"""

MAX_PATCH_BYTES = 256 * 1024
"""How much of a task's patch is kept; past it, the files that follow have no hunks."""

MAX_FILES = 500
"""How many changed files are listed; past it, only how many more there were."""

MAX_LIST_BYTES = 512 * 1024
"""How much of each half of the file list is read back; past it, files are counted, not listed."""

MAX_SIZE_DIGITS = 15
"""The longest number `parse` reads - a size line, or one file's line count: anything a sandbox holds fits well inside."""

MAX_COUNT = 2**31 - 1
"""The most files a change set says it left out - what its column holds."""

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
    'GIT_WORK_TREE="$PWD" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_ATTR_NOSYSTEM=1 '
    "GIT_OPTIONAL_LOCKS=0 "
    # Defence in depth, not a closed channel: the store is the task's user's to
    # write, so its config can still name a clean filter or an include. These
    # two are the ones git runs on its own; whatever any of them prints, or any
    # process of that user writes here, `parse` bounds.
    "GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=core.fsmonitor GIT_CONFIG_VALUE_0=false "
    "GIT_CONFIG_KEY_1=core.hooksPath GIT_CONFIG_VALUE_1=/dev/null; "
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

# The private info file outranks workspace attributes: these are byte snapshots,
# not Git checkouts subject to clean filters, encodings or newline conversion.
BEGIN = (
    f'{_SETUP}set -e; umask 077; rm -rf "${STORE_ENV}"; mkdir -p "${STORE_ENV}"; git init -q; '
    f"printf '%s\\n' '* -text -filter -ident -working-tree-encoding' > \"${STORE_ENV}/git/info/attributes\"; "
    f"{_SNAPSHOT}"
)
"""Make the task's store and snapshot the workspace into it; prints the tree."""

_DIFF = (
    f'git -c core.quotepath=off diff-tree -r -M --no-ext-diff --no-textconv "${BASE_ENV}" "$after"'
)

FINISH = (
    f"{_SETUP}set -e; after=$({_SNAPSHOT}); "
    f'{_DIFF} -z --raw > "${STORE_ENV}/raw"; '
    f'{_DIFF} -z --numstat > "${STORE_ENV}/num"; '
    # Only as much of the patch as is kept is ever written: git stops on the
    # closed pipe (141), and any other exit is a diff that could not be made.
    f'{{ if {_DIFF} -p --binary --full-index --no-color; then echo 0 > "${STORE_ENV}/rc"; '
    f'else echo $? > "${STORE_ENV}/rc"; fi; }} '
    f'| head -c {MAX_PATCH_BYTES + 1} > "${STORE_ENV}/patch"; '
    f'rc=$(cat "${STORE_ENV}/rc"); [ "$rc" = 0 ] || [ "$rc" = 141 ] || exit 1; '
    f'wc -c < "${STORE_ENV}/raw"; wc -c < "${STORE_ENV}/num"; wc -c < "${STORE_ENV}/patch"; '
    # One `:`-led metadata line per file in the `--raw` list: how many there are, listed or not.
    f"{{ tr '\\000' '\\n' < \"${STORE_ENV}/raw\" | grep -c '^:[0-7]* [0-7]* ' || true; }}; "
    f"head -c {MAX_LIST_BYTES} \"${STORE_ENV}/raw\" | base64 | tr -d '\\n'; echo; "
    f"head -c {MAX_LIST_BYTES} \"${STORE_ENV}/num\" | base64 | tr -d '\\n'; echo; "
    f"head -c {MAX_PATCH_BYTES} \"${STORE_ENV}/patch\" | base64 | tr -d '\\n'; echo; "
    # Count both blob states, including mode-only changes and repeated blobs.
    # A small compressed patch need not mean a small verification workload.
    f"{_DIFF} --no-renames --raw "
    "| awk '/^:/ {if ($3 !~ /^0+$/) print $3; if ($4 !~ /^0+$/) print $4}' "
    "| git cat-file --batch-check='%(objectsize)' "
    f"| awk '{{total += $1; if ($0 !~ /^[0-9]+$/ || $1 > {MAX_REVERT_FILE_BYTES}) bad=1}} "
    f"END {{print (bad || total > {MAX_REVERT_BYTES}) ? 0 : 1}}'"
)
"""Snapshot again and print the change, a line each: the sizes of the `--raw` list, the
`--numstat` list and the patch, the file count, each list's head (base64), the patch,
and whether its before/after blobs fit the revert verification limits.

The lists are written to the store first, so `set -e` sees `diff-tree` fail -
piped straight out, a failing one printed nothing and read as a task that
changed nothing. The list sizes are the bytes git wrote; the patch's is what
`head` kept of it, one byte past the ceiling when there was more.
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
            # The exit code alone: stderr is the sandbox's, and a task that rewrote
            # the store's git config can make it print the workspace.
            logger.warning(
                "A coding task's workspace could not be snapshotted (exit %s)", result.exit_code
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
        # The exit code alone, as in `begin`: stderr is the sandbox's to write.
        logger.warning("A coding task's changes could not be read (exit %s)", result.exit_code)
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
    """The change set `FINISH` printed, or `None` for output that is not one.

    Bounded here as well as in the shell: the output comes out of a sandbox the
    task ran in, and whatever the task left running there can write into it. So
    no size line is read past `MAX_SIZE_DIGITS`, no list past what `head` would
    have sent, and no patch past `MAX_PATCH_BYTES` characters - the shell's
    bytes, as many or fewer once decoded.
    """
    head = stdout.split("\n", 7)
    if len(head) < 7:
        return None
    # Older capture output has seven lines; new captures append the workload flag.
    bounded = True
    if len(head) == 8:
        bounds = head.pop().strip()
        if bounds not in {"0", "1"}:
            return None
        bounded = bounds == "1"
    *sizes, raw_text, num_text, encoded_patch = head
    if not all(size.strip().isdecimal() and len(size.strip()) <= MAX_SIZE_DIGITS for size in sizes):
        return None
    raw_size, num_size, patch_size, total = (int(size) for size in sizes)
    raw = _decoded(raw_text)
    counts = _decoded(num_text)
    if raw is None or counts is None:
        return None
    if len(encoded_patch) > (MAX_PATCH_BYTES + 2) // 3 * 4:
        return None
    try:
        patch_bytes = base64.b64decode(encoded_patch, validate=True)
    except binascii.Error, ValueError:
        return None
    patch = patch_bytes.decode("utf-8", errors="replace")
    listed = raw_size <= MAX_LIST_BYTES and num_size <= MAX_LIST_BYTES
    entries = _entries(raw, counts, complete=listed)
    if entries is None:
        return None
    cut = patch_size > MAX_PATCH_BYTES or len(patch_bytes) > MAX_PATCH_BYTES
    sections = _sections(patch[:MAX_PATCH_BYTES].replace("\x00", ""), cut=cut)
    _attach(entries, sections, cut=cut, listed=listed)
    kept = [entry for entry, _ in entries[:MAX_FILES]]
    omitted = min(max(total if not listed else 0, len(entries)) - len(kept), MAX_COUNT)
    hunkless = any(entry.patch is None for entry in kept)
    truncated = cut or omitted > 0 or hunkless
    return ChangeSet(
        files=kept,
        omitted=omitted,
        truncated=truncated,
        revert_patch=encoded_patch if kept and not truncated and bounded else None,
    )


def _decoded(text: str) -> list[str] | None:
    """One list's NUL-separated fields, the last one dropped unless it was terminated."""
    text = text.strip()
    if len(text) > (MAX_LIST_BYTES + 2) // 3 * 4:
        return None
    try:
        raw = base64.b64decode(text, validate=True)
    except binascii.Error, ValueError:
        return None
    return raw.decode("utf-8", errors="replace").split("\x00")[:-1]


def _entries(
    raw: list[str], counts: list[str], *, complete: bool
) -> list[tuple[ChangedFile, int]] | None:
    """`--raw -z` and `--numstat -z`: each file in git's order, with how many parts of the patch it has.

    A type change - a file become a link - is one file and two parts. A list cut
    short by `MAX_LIST_BYTES` gives the files both halves hold whole; a complete
    one that does not parse is no change set at all.
    """
    files: list[tuple[ChangedFile, int]] = []
    position = 0
    while position < len(raw):
        if not raw[position].startswith(":"):
            return None
        metadata = raw[position][1:].split(" ")
        if len(metadata) != 5:
            return None
        before_mode, after_mode, before_blob, after_blob, status = metadata
        if not _is_object_id(before_blob) or not _is_object_id(after_blob):
            return None
        code = status[:1]
        renamed = code in ("R", "C")
        width = 3 if renamed else 2
        if position + width > len(raw):
            if complete:
                return None
            break
        names = raw[position + 1 : position + width]
        entry = ChangedFile(
            path=names[-1],
            old_path=names[0] if renamed else None,
            status=_STATUS.get(code, "modified"),
            before_blob=before_blob,
            after_blob=after_blob,
            before_mode=before_mode,
            after_mode=after_mode,
        )
        files.append((entry, 2 if code == "T" else 1))
        position += width
    position = 0
    for index, (entry, _) in enumerate(files):
        # A rename's counts end in an empty path, its two names in the next fields.
        width = 3 if entry.old_path is not None else 1
        if position + width > len(counts):
            if complete:
                return None
            return files[:index]
        added, _, rest = counts[position].partition("\t")
        deleted, _, _ = rest.partition("\t")
        position += width
        entry.binary = added == "-"
        entry.additions = int(added) if added.isdecimal() and len(added) <= MAX_SIZE_DIGITS else 0
        entry.deletions = (
            int(deleted) if deleted.isdecimal() and len(deleted) <= MAX_SIZE_DIGITS else 0
        )
    return files


def _sections(patch: str, *, cut: bool) -> list[str]:
    """The patch split at each `diff --git` header, the part a cut left open dropped back to a line.

    Split on `\n` alone: `str.splitlines` also breaks at a form feed or a
    `\x1c`, which file content may hold, and content could then open a section
    of its own and move every later file's hunks under the wrong name.
    """
    if cut:
        patch = patch[: patch.rfind("\n") + 1]
    sections: list[list[str]] = []
    for line in patch.split("\n")[:-1]:
        if line.startswith("diff --git ") or not sections:
            sections.append([])
        sections[-1].append(line)
    return ["".join(f"{line}\n" for line in section) for section in sections]


def _attach(
    files: list[tuple[ChangedFile, int]], sections: list[str], *, cut: bool, listed: bool
) -> None:
    """Give each file its part of the patch, a type change taking two.

    The parts are git's own order, so they line up with the files - unless the
    count says otherwise, when no file is given parts that may be another's. A
    list cut short has more parts than files; a patch cut short, fewer.
    """
    wanted = sum(parts for _, parts in files)
    too_many = listed and len(sections) > wanted
    too_few = not cut and len(sections) < wanted
    if too_many or too_few:
        logger.warning("A coding task's patch did not line up with its files; hunks left out")
        return
    position = 0
    for entry, parts in files:
        taken = sections[position : position + parts]
        position += parts
        if not taken:
            return
        entry.patch = "".join(taken)
        # The file the cut fell in took the last part there is.
        entry.truncated = cut and position >= len(sections)
        if entry.truncated:
            entry.patch += TRUNCATED_MARKER


def _is_object_id(text: str) -> bool:
    return len(text) in (40, 64) and all(char in "0123456789abcdef" for char in text)
