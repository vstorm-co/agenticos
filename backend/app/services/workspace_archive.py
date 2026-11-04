"""Archives into a workspace and out of one (#2479).

**In.** A `.zip` or `.tar.gz` attached to an agent with a workspace is unpacked
into it *here, on the server*, rather than handed over for the agent to unpack.
Two reasons. A `state` workspace has no shell, so "unpack it yourself" fails on
the default backend, and a sandbox image is not promised to carry `unzip`. And
an archive is the classic way to smuggle a write outside a directory - a `../`
member, an absolute path, a symlink a later member writes through, a device
node, a few kilobytes that inflate to gigabytes. Checking all of that once, in
one function, before a single byte lands is something that can be tested; an
agent running `tar -xf` on whatever it was given is not.

So :func:`read_archive` validates the whole archive and returns its members, and
nothing is written unless every member passed. The members are then written
through the workspace's own `write_bytes` - the path every other attachment
takes, so the workspace's own confinement to its root still applies underneath.

**Out.** :func:`stream_zip` turns a folder's files into a `.zip` one file at a
time, so a download of a folder is never held whole in memory.

Both directions share one set of bounds: `WORKSPACE_ARCHIVE_MAX_ENTRIES` and
`WORKSPACE_ARCHIVE_MAX_BYTES`, and the unpacking side also
`WORKSPACE_ARCHIVE_MAX_RATIO`.
"""

import gzip
import io
import logging
import re
import stat
import tarfile
import zipfile
import zlib
from collections.abc import AsyncIterator, Awaitable, Buffer, Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import IO, Literal

from pydantic_ai.workspaces import Workspace

from app.core.blocking import run_blocking
from app.core.config import settings
from app.core.exceptions import BadRequestError, ExportTooLargeError

logger = logging.getLogger(__name__)

ArchiveFormat = Literal["zip", "targz"]

ARCHIVE_SUFFIXES: tuple[tuple[str, ArchiveFormat], ...] = (
    (".tar.gz", "targz"),
    (".tgz", "targz"),
    (".zip", "zip"),
)
"""The names an archive may carry, longest first so `.tar.gz` is not read as `.gz`."""

_CHUNK = 1024 * 1024
"""How much of a member is read at a time while its real size is measured."""

_TAR_OVERHEAD_PER_ENTRY = 2048
"""What a tar spends around one member: a 512-byte header, a PAX header for a
long name, and up to 511 bytes of padding. Bounds the decompressed stream, which
carries those as well as the contents the byte limit counts."""

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class ArchiveMember:
    """One entry of a validated archive: a file and its bytes, or a folder."""

    path: str
    """Relative, `/`-separated, with no `.` or `..` part and no leading slash."""
    data: bytes = b""
    is_dir: bool = False


def archive_format(filename: str) -> ArchiveFormat | None:
    """Which archive a filename names, or `None` when it names none."""
    lowered = filename.lower()
    for suffix, fmt in ARCHIVE_SUFFIXES:
        if lowered.endswith(suffix):
            return fmt
    return None


def unpacked_name(filename: str) -> str:
    """The name of the folder an archive unpacks into: its own, without the suffix."""
    lowered = filename.lower()
    for suffix, _fmt in ARCHIVE_SUFFIXES:
        if lowered.endswith(suffix) and len(filename) > len(suffix):
            return filename[: -len(suffix)]
    return filename


def _refused(message: str, **details: object) -> BadRequestError:
    return BadRequestError(message=message, details=details)


def safe_member_path(name: str) -> str | None:
    """A member's name as a relative path inside the folder, or `None` for the root itself.

    Refused rather than repaired: an archive whose names climb out of it, start
    at the filesystem root or a Windows drive, use a backslash (a separator on
    one system and a filename character on another, so the two disagree about
    where it lands) or hide control characters was built to do something other
    than carry a tree, and rewriting its names would unpack a different tree from
    the one it describes.

    Raises:
        BadRequestError: If the name is unsafe.
    """
    if _CONTROL.search(name) or "\\" in name:
        raise _refused("The archive holds a file name with characters that are not allowed.")
    if name.startswith("/") or _DRIVE.match(name):
        raise _refused("The archive holds an absolute path, which cannot be unpacked safely.")
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if ".." in parts:
        raise _refused("The archive holds a path that leads outside it (`..`).")
    return "/".join(parts) or None


class _Tree:
    """The members seen so far, and the bounds they spend."""

    def __init__(self, compressed: int) -> None:
        self.members: list[ArchiveMember] = []
        self.files: set[str] = set()
        self.dirs: set[str] = set()
        self.ancestors: set[str] = set()
        """Every folder some member sits in, named or not."""
        self.total = 0
        self.compressed = max(compressed, 1)

    def _claim(self, path: str) -> None:
        """Count one more entry, and refuse a path another member already holds.

        A path twice, or one path as both a file and a folder, means an archive
        whose last word decides what lands - and which member is the last is not
        the same question for every unpacker.
        """
        if len(self.members) >= settings.WORKSPACE_ARCHIVE_MAX_ENTRIES:
            raise _refused(
                "The archive holds too many files.",
                max_entries=settings.WORKSPACE_ARCHIVE_MAX_ENTRIES,
            )
        parents = {str(parent) for parent in PurePosixPath(path).parents} - {"."}
        if path in self.files or not parents.isdisjoint(self.files):
            raise _refused("The archive holds the same path twice, or as both a file and a folder.")
        self.ancestors |= parents

    def add_dir(self, path: str | None) -> None:
        if path is None or path in self.dirs:
            return
        self._claim(path)
        self.dirs.add(path)
        self.members.append(ArchiveMember(path=path, is_dir=True))

    def add_file(self, path: str | None, stream: IO[bytes]) -> None:
        if path is None:
            raise _refused("The archive holds a file with no name.")
        if path in self.dirs or path in self.ancestors:
            raise _refused("The archive holds the same path twice, or as both a file and a folder.")
        self._claim(path)
        chunks: list[bytes] = []
        while chunk := stream.read(_CHUNK):
            self.total += len(chunk)
            self._check_size()
            chunks.append(chunk)
        self.files.add(path)
        self.members.append(ArchiveMember(path=path, data=b"".join(chunks)))

    def _check_size(self) -> None:
        if self.total > settings.WORKSPACE_ARCHIVE_MAX_BYTES:
            raise _refused(
                "The archive is too large once unpacked.",
                max_bytes=settings.WORKSPACE_ARCHIVE_MAX_BYTES,
            )
        if self.total > self.compressed * settings.WORKSPACE_ARCHIVE_MAX_RATIO:
            raise _refused(
                "The archive unpacks to far more than its own size, the shape of a "
                "decompression bomb.",
                max_ratio=settings.WORKSPACE_ARCHIVE_MAX_RATIO,
            )


def _zip_members(data: bytes, tree: _Tree) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > settings.WORKSPACE_ARCHIVE_MAX_ENTRIES:
            raise _refused(
                "The archive holds too many files.",
                max_entries=settings.WORKSPACE_ARCHIVE_MAX_ENTRIES,
            )
        for info in infos:
            if info.flag_bits & 0x1:
                raise _refused("The archive is encrypted, and cannot be unpacked.")
            # The Unix mode a zip made on Unix keeps in the top half of the
            # external attributes. Zero is "not recorded" - a zip made on Windows.
            kind = stat.S_IFMT(info.external_attr >> 16)
            if info.is_dir() or kind == stat.S_IFDIR:
                tree.add_dir(safe_member_path(info.filename))
                continue
            if kind not in (0, stat.S_IFREG):
                raise _refused(
                    "The archive holds a link or a special file, which cannot be unpacked safely."
                )
            with archive.open(info) as member:
                tree.add_file(safe_member_path(info.filename), member)


class _Bounded(io.RawIOBase):
    """A stream that refuses to give out more than `limit` bytes.

    The tar's decompressed stream is bounded as a whole, headers and padding
    included, so a gzip bomb stops being inflated at the bound rather than once
    the contents the per-member count sees have added up.
    """

    def __init__(self, inner: io.BufferedIOBase, limit: int) -> None:
        self._inner = inner
        self._left = limit

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int:
        view = memoryview(buffer)
        data = self._inner.read(len(view))
        if len(data) > self._left:
            raise _refused(
                "The archive is too large once unpacked.",
                max_bytes=settings.WORKSPACE_ARCHIVE_MAX_BYTES,
            )
        self._left -= len(data)
        view[: len(data)] = data
        return len(data)


def _tar_members(data: bytes, tree: _Tree) -> None:
    limit = min(
        settings.WORKSPACE_ARCHIVE_MAX_BYTES
        + settings.WORKSPACE_ARCHIVE_MAX_ENTRIES * _TAR_OVERHEAD_PER_ENTRY
        + _CHUNK,
        len(data) * settings.WORKSPACE_ARCHIVE_MAX_RATIO + _CHUNK,
    )
    stream = io.BufferedReader(_Bounded(gzip.GzipFile(fileobj=io.BytesIO(data)), limit))
    # `r|`: one pass over the stream, every member read as it is reached.
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            if member.isdir():
                tree.add_dir(safe_member_path(member.name))
                continue
            if not member.isreg():
                raise _refused(
                    "The archive holds a link or a special file, which cannot be unpacked safely."
                )
            extracted = archive.extractfile(member)
            if extracted is None:  # pragma: no cover - a regular member always has a reader
                raise _refused("The archive could not be read.")
            tree.add_file(safe_member_path(member.name), extracted)


def read_archive(data: bytes, fmt: str) -> list[ArchiveMember]:
    """Every member of an archive, once the whole archive has been checked.

    `fmt` is the format `resolve_format` gave the upload: `zip`, or `targz`.

    Blocking - it inflates the archive - so a caller on the event loop runs it
    through `run_blocking`. Each member is read through a bounded stream rather
    than trusting the size its header declares, which an archive may lie about.

    Raises:
        BadRequestError: If the archive is unsafe, too large, or cannot be read.
            Nothing is returned for an archive with even one bad member.
    """
    tree = _Tree(len(data))
    try:
        if fmt == "zip":
            _zip_members(data, tree)
        else:
            _tar_members(data, tree)
    except BadRequestError:
        raise
    except (
        zipfile.BadZipFile,
        tarfile.TarError,
        gzip.BadGzipFile,
        zlib.error,
        EOFError,
        NotImplementedError,
        RuntimeError,
        OSError,
        ValueError,
    ) as exc:
        logger.info("archive_unreadable", extra={"format": fmt, "reason": type(exc).__name__})
        name = ".zip" if fmt == "zip" else ".tar.gz"
        raise _refused(f"The file could not be read as a {name} archive.") from None
    return tree.members


def manifest(members: Sequence[ArchiveMember]) -> str:
    """What an archive holds, as text: a count line, then one path per line.

    Kept as the attachment's parsed text, so the reference a model is given
    opens on the top of the tree the way a document's opens on its first lines.
    """
    files = [member for member in members if not member.is_dir]
    size = sum(len(member.data) for member in files)
    lines = [f"{len(files)} files, {size} bytes unpacked"]
    lines.extend(f"{member.path}/" if member.is_dir else member.path for member in members)
    return "\n".join(lines)


async def unpack_into(workspace: Workspace, root: str, members: Sequence[ArchiveMember]) -> None:
    """Write validated members under `root`, or leave nothing there at all.

    A write the workspace refuses part-way - a full document, a host that went
    away - removes what was already written before the error goes on. A partial
    tree under the folder's name would otherwise read, to the next turn's
    `exists`, as an archive already unpacked.

    Raises:
        OSError, WorkspaceError: Whatever the workspace raised for the write.
    """
    try:
        await workspace.make_dir(root)
        for member in members:
            target = f"{root}/{member.path}"
            if member.is_dir:
                await workspace.make_dir(target)
            else:
                await workspace.write_bytes(target, member.data)
    except Exception:
        try:
            await workspace.remove(root)
        except Exception:
            logger.warning("archive_partial_not_removed", extra={"root": root}, exc_info=True)
        raise


class _Sink(io.RawIOBase):
    """Where `zipfile` writes, drained after each member so the zip streams.

    Not seekable, so `zipfile` writes each member's sizes after its data rather
    than going back to patch its header - which is what lets a member leave
    before the next one is read.
    """

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._offset = 0

    def write(self, data: Buffer) -> int:
        chunk = bytes(data)
        self._chunks.append(chunk)
        self._offset += len(chunk)
        return len(chunk)

    def tell(self) -> int:
        return self._offset

    def drain(self) -> bytes:
        chunk, self._chunks = b"".join(self._chunks), []
        return chunk


def _add(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    archive.writestr(info, data)


async def stream_zip(
    members: Sequence[tuple[str, str]], read: Callable[[str], Awaitable[bytes]]
) -> AsyncIterator[bytes]:
    """A `.zip` of `members`, yielded one member at a time.

    Args:
        members: Each file's path in the workspace, and its name in the zip.
        read: Reads one workspace path's bytes.

    The listing the members came from was bounded before the response started;
    the bytes are bounded again as they are read, because a file can grow
    between the listing and the read. Past the bound the stream stops, and the
    client is left with a zip that does not open rather than one that silently
    lacks files.
    """
    sink = _Sink()
    total = 0
    with zipfile.ZipFile(sink, "w") as archive:
        for path, name in members:
            data = await read(path)
            total += len(data)
            if total > settings.WORKSPACE_ARCHIVE_MAX_BYTES:
                raise _refused(
                    "The folder grew past the download limit while it was being zipped.",
                    max_bytes=settings.WORKSPACE_ARCHIVE_MAX_BYTES,
                )
            await run_blocking(_add, archive, name, data)
            yield sink.drain()
    yield sink.drain()


def zip_folder(folder: str) -> str:
    """A folder to download, as the listing spells it with `./` and slashes taken off.

    Raises:
        BadRequestError: If it climbs out of the workspace.
    """
    wanted = _normal(folder)
    if ".." in wanted.split("/"):
        raise _refused("A folder path cannot lead outside the workspace.", folder=folder)
    return wanted


def zip_members(
    entries: Iterable[tuple[str, int | None]], folder: str
) -> tuple[list[tuple[str, str]], str]:
    """Which files a folder's zip holds, and the name of the zip.

    Args:
        entries: Each listed file's path and size, as the listing spells it.
        folder: The folder, from :func:`zip_folder`; empty for the whole workspace.

    Returns:
        Each file's workspace path and its name inside the zip - under a top
        folder named after the one downloaded, so unzipping it does not scatter
        files into wherever it was saved - and the zip's own name.

    Raises:
        ExportTooLargeError: If the folder holds more files or bytes than one
            download may carry.
    """
    top = folder.rsplit("/", 1)[-1] if folder else "workspace"
    picked: list[tuple[str, str]] = []
    total = 0
    for path, size in entries:
        relative = _normal(path)
        if folder and not relative.startswith(f"{folder}/"):
            continue
        inside = relative[len(folder) + 1 :] if folder else relative
        picked.append((path, f"{top}/{inside}"))
        total += size or 0
        if (
            len(picked) > settings.WORKSPACE_ARCHIVE_MAX_ENTRIES
            or total > settings.WORKSPACE_ARCHIVE_MAX_BYTES
        ):
            raise ExportTooLargeError(
                message="This folder is too large to download as one zip. Download a smaller folder.",
                details={
                    "max_entries": settings.WORKSPACE_ARCHIVE_MAX_ENTRIES,
                    "max_bytes": settings.WORKSPACE_ARCHIVE_MAX_BYTES,
                },
            )
    return picked, f"{top}.zip"


def _normal(path: str) -> str:
    """A listing's path with the spellings backends differ on taken off: `./`, `/`."""
    stripped = path.strip()
    while stripped.startswith("./"):
        stripped = stripped[2:]
    return stripped.strip("/")
