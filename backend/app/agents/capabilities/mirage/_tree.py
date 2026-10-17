"""A read-only folder Mirage can mount, over files the platform lists and reads.

Mirage ships resources for the stores it knows - RAM, GitHub, S3 and the rest.
A knowledge base is not one of them, and a sync source reaches its store
through the platform's own connector with the organization's credential, so
both are mounted through Mirage's `GenericResource`: a flat listing and a
reader, which this module turns into the directory operations Mirage's shell
calls.

What the shell prints for a failure is the exception's text, and a connector's
exception can carry a bucket policy, a URL with a signature in it or a token
echoed back by an API. So nothing from the runner's callables reaches the model
except `TreeUnavailable.message`, a sentence this repository wrote; anything
else is logged and replaced.
"""

from __future__ import annotations

import errno
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from mirage.accessor.base import Accessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.commands.builtin.generic_bind.adapter import CommandIO
from mirage.resource.generic import GenericResource
from mirage.types import FileStat, FileType, PathSpec
from mirage.utils.errors import enoent
from mirage.utils.key_prefix import mount_prefix_of
from mirage.utils.path import norm

logger = logging.getLogger(__name__)


class TreeUnavailable(Exception):
    """A listing or a read the source refused, in words the model may see."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class TreeFile:
    """One file of a mounted folder: where it sits under the mount, and its size if known."""

    path: str
    size: int | None = None


async def _nothing() -> None:
    return None


@dataclass(frozen=True)
class MountedTree:
    """One read-only folder of the terminal, as the runner resolved it.

    `list_files` is called once per run, on the first command that reaches the
    folder - a sync source's listing is a request to its store, and a run that
    never looks should not have made it. `read_file` takes a path as
    `list_files` answered it. `close` releases what the listing opened, a
    clone or a session, when the run ends.
    """

    path: str
    describe: str
    list_files: Callable[[], Awaitable[Sequence[TreeFile]]]
    read_file: Callable[[str], Awaitable[bytes]]
    close: Callable[[], Awaitable[None]] = field(default=_nothing)


def _refused(tree: MountedTree, what: str, error: Exception) -> OSError:
    """The error the shell prints: the source's own sentence, or a generic one."""
    if isinstance(error, TreeUnavailable):
        return OSError(errno.EACCES, error.message)
    logger.warning("mirage_tree_failed", extra={"mount": tree.path, "op": what}, exc_info=error)
    return OSError(errno.EIO, f"{tree.path} could not be {what}; try again later")


@dataclass
class _Index:
    """A tree's listing, read once: its files and every directory above them."""

    files: dict[str, int | None]
    dirs: set[str]


def _indexed(files: Sequence[TreeFile]) -> _Index:
    index = _Index(files={}, dirs={"/"})
    for entry in files:
        path = "/" + entry.path.strip("/")
        index.files[path] = entry.size
        parts = path.strip("/").split("/")[:-1]
        for depth in range(len(parts)):
            index.dirs.add("/" + "/".join(parts[: depth + 1]))
    return index


def tree_resource(tree: MountedTree) -> GenericResource:
    """`tree` as a Mirage resource that lists, stats and reads, and writes nothing.

    One per run: the listing is cached on the resource, so a second `ls` costs
    nothing and a file added upstream mid-run is not seen until the next one.
    """
    cached: _Index | None = None

    async def listing() -> _Index:
        nonlocal cached
        if cached is None:
            try:
                cached = _indexed(await tree.list_files())
            except Exception as error:
                raise _refused(tree, "listed", error) from None
        return cached

    async def readdir(
        accessor: Accessor, path: PathSpec, index: IndexCacheStore = NULL_INDEX
    ) -> list[str]:
        target = path.dir if path.pattern else path
        prefix = mount_prefix_of(target.virtual, target.resource_path)
        here = norm(target.resource_path)
        known = await listing()
        if here not in known.dirs:
            raise enoent(path.virtual)
        base = here.rstrip("/") + "/"
        children = sorted(
            {
                base + entry[len(base) :].split("/")[0]
                for entry in (*known.files, *known.dirs)
                if entry.startswith(base) and entry != here
            }
        )
        return [prefix + child for child in children]

    async def stat(
        accessor: Accessor, path: PathSpec, index: IndexCacheStore = NULL_INDEX
    ) -> FileStat:
        here = norm(path.resource_path)
        known = await listing()
        name = here.rsplit("/", 1)[-1] or "/"
        if here in known.dirs:
            return FileStat(name=name, type=FileType.DIRECTORY)
        if here in known.files:
            return FileStat(name=name, size=known.files[here], type=FileType.FILE)
        raise enoent(path.virtual)

    async def read_bytes(
        accessor: Accessor, path: PathSpec, index: IndexCacheStore = NULL_INDEX
    ) -> bytes:
        # The shell stats a path before it reads one, so a name the listing
        # does not hold has already been answered "No such file" by `stat`.
        try:
            return await tree.read_file(norm(path.resource_path).lstrip("/"))
        except Exception as error:
            raise _refused(tree, "read", error) from None

    async def read_stream(
        accessor: Accessor, path: PathSpec, index: IndexCacheStore = NULL_INDEX
    ) -> AsyncIterator[bytes]:
        yield await read_bytes(accessor, path, index)

    io = CommandIO(
        readdir=readdir,
        read_bytes=read_bytes,
        read_stream=read_stream,
        stat=stat,
        is_mounted=lambda accessor: True,
    )
    return GenericResource(
        name=tree.path.strip("/"), accessor=Accessor(), io=io, prompt=tree.describe
    )
