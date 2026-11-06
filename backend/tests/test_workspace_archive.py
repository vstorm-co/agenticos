"""Archives into a workspace and out of one (#2479).

The refusals are the point. An archive is the classic way to write outside a
directory - a `../` member, an absolute path, a link a later member writes
through, a device node - and the classic way to spend a server's memory, with a
few kilobytes that inflate to gigabytes. Each is refused before one byte lands.
"""

import asyncio
import io
import stat
import tarfile
import threading
import zipfile
from unittest.mock import AsyncMock

import anyio
import pytest
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.core.config import settings
from app.core.exceptions import BadRequestError, ExportTooLargeError, NotFoundError
from app.services import workspace_archive
from app.services.workspace_archive import (
    NOT_INCLUDED,
    ArchiveMember,
    manifest,
    safe_member_path,
    scan_archive,
    stream_zip,
    unpack_into,
    unpacked_name,
    zip_folder,
    zip_members,
)
from tests.workspaces import ShellFailing, document_workspace

pytestmark = pytest.mark.anyio


def _zip(*members: tuple[str, bytes], mode: int | None = None, encrypted: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, data)
    data = bytearray(buffer.getvalue())
    if encrypted:
        # `zipfile` cannot write an encrypted member, so the flag is set by hand
        # in the central directory, which is what a reader trusts.
        directory = data.index(b"PK\x01\x02")
        data[directory + 8] |= 0x1
    return bytes(data)


def _tar(*members: tarfile.TarInfo | tuple[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for member in members:
            if isinstance(member, tarfile.TarInfo):
                archive.addfile(member)
            else:
                name, data = member
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _special(name: str, kind: bytes, linkname: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = linkname
    return info


async def _unpacked(data: bytes, fmt: str) -> dict[str, bytes]:
    """What unpacking `data` writes, read back out of a stored workspace."""
    document = CappedStateBackend(max_bytes=64 * 1024 * 1024)
    await unpack_into(document_workspace(document), "root", data, fmt)
    return {
        path.removeprefix("/root/"): document.read_bytes(path)
        for path in document.files
        if path.startswith("/root/")
    }


REPO = (
    ("repo/README.md", b"# repo\n"),
    ("repo/src/app.py", b"print('hi')\n"),
    ("repo/tests/test_app.py", b"def test_it():\n    assert True\n"),
)


class TestTheNamesAnArchiveCarries:
    def test_the_folder_is_named_after_the_archive(self):
        assert unpacked_name("repo.tar.gz") == "repo"
        assert unpacked_name("repo.zip") == "repo"
        # A name that is only the suffix keeps it rather than becoming nothing.
        assert unpacked_name(".zip") == ".zip"
        assert unpacked_name("notes.txt") == "notes.txt"


class TestASafeArchiveUnpacksToTheSameTree:
    async def test_a_zip(self):
        data = _zip(*REPO, ("repo/empty/", b""))
        members = scan_archive(data, "zip")

        assert {m.path: m.size for m in members if not m.is_dir} == {
            path: len(body) for path, body in REPO
        }
        # A scan keeps sizes, never bytes.
        assert all(member.data == b"" for member in members)
        assert ArchiveMember(path="repo/empty", is_dir=True) in members
        assert await _unpacked(data, "zip") == dict(REPO)

    async def test_a_tar_gz(self):
        folder = tarfile.TarInfo("./repo/docs")
        folder.type = tarfile.DIRTYPE
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        data = _tar(root, folder, folder, *REPO)
        members = scan_archive(data, "targz")

        assert await _unpacked(data, "targz") == dict(REPO)
        # The root entry `.` is not a folder of its own, and a folder named twice is one.
        assert [member.path for member in members if member.is_dir] == ["repo/docs"]

    def test_a_zip_root_entry_is_not_a_folder_of_its_own(self):
        assert [m.path for m in scan_archive(_zip(("./", b""), ("a.txt", b"1")), "zip")] == [
            "a.txt"
        ]

    def test_the_manifest_opens_on_a_count_and_lists_the_tree(self):
        text = manifest(scan_archive(_zip(*REPO, ("repo/empty/", b"")), "zip"))

        assert text.splitlines()[0] == "3 files, 50 bytes unpacked"
        assert "repo/src/app.py" in text
        assert "repo/empty/" in text


@pytest.mark.security
class TestAnArchiveThatWritesOutsideIsRefused:
    @pytest.mark.parametrize(
        "name",
        [
            "../escape.txt",
            "repo/../../escape.txt",
            "/etc/passwd",
            "C:/Windows/x",
            "a\\..\\b",
            "bad\x01name",
        ],
    )
    def test_a_member_name_that_leaves_the_folder(self, name):
        with pytest.raises(BadRequestError):
            scan_archive(_zip((name, b"x")), "zip")

    def test_a_tar_member_that_climbs_out(self):
        with pytest.raises(BadRequestError, match=r"\.\."):
            scan_archive(_tar(("../../etc/cron.d/x", b"x")), "targz")

    @pytest.mark.parametrize(
        "member",
        [
            _special("repo/link", tarfile.SYMTYPE, "/etc/passwd"),
            _special("repo/hard", tarfile.LNKTYPE, "repo/README.md"),
            _special("repo/dev", tarfile.CHRTYPE),
            _special("repo/disk", tarfile.BLKTYPE),
            _special("repo/pipe", tarfile.FIFOTYPE),
        ],
    )
    def test_a_link_or_a_device_in_a_tar(self, member):
        with pytest.raises(BadRequestError, match="link or a special file"):
            scan_archive(_tar(member), "targz")

    def test_a_symlink_in_a_zip(self):
        with pytest.raises(BadRequestError, match="link or a special file"):
            scan_archive(_zip(("repo/link", b"/etc/passwd"), mode=stat.S_IFLNK | 0o777), "zip")

    def test_a_zip_entry_marked_a_folder_by_its_mode_is_a_folder(self):
        members = scan_archive(_zip(("repo/dir", b""), mode=stat.S_IFDIR | 0o755), "zip")

        assert members == [ArchiveMember(path="repo/dir", is_dir=True)]

    def test_an_encrypted_zip(self):
        with pytest.raises(BadRequestError, match="encrypted"):
            scan_archive(_zip(("a.txt", b"x"), encrypted=True), "zip")

    @pytest.mark.parametrize(
        "members",
        [
            (("a.txt", b"1"), ("a.txt", b"2")),
            (("a", b"1"), ("a/b", b"2")),
            (("a/b", b"1"), ("a", b"2")),
            (("a/", b""), ("a", b"2")),
        ],
    )
    def test_one_path_twice(self, members):
        with pytest.raises(BadRequestError, match="same path twice"):
            scan_archive(_zip(*members), "zip")

    def test_a_folder_named_where_a_file_is(self):
        with pytest.raises(BadRequestError, match="same path twice"):
            scan_archive(_zip(("a", b"1"), ("a/", b"")), "zip")

    def test_a_file_with_no_name(self):
        with pytest.raises(BadRequestError, match="no name"):
            scan_archive(_tar(("./", b"x")), "targz")


@pytest.mark.security
class TestAnArchiveThatSpendsTheServerIsRefused:
    def test_a_zip_bomb_by_ratio(self):
        with pytest.raises(BadRequestError, match="decompression bomb"):
            scan_archive(_zip(("zeros", b"\0" * (4 * 1024 * 1024))), "zip")

    def test_a_tar_gz_bomb_stops_inflating_at_the_bound(self, monkeypatch):
        # The members' own count never gets to see it: the stream is bounded first.
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_RATIO", 1)
        with pytest.raises(BadRequestError, match="too large once unpacked"):
            scan_archive(_tar(("zeros", b"\0" * (4 * 1024 * 1024))), "targz")

    def test_past_the_byte_limit(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_BYTES", 10)
        with pytest.raises(BadRequestError, match="too large once unpacked"):
            scan_archive(_zip(("a.txt", b"x" * 11)), "zip")

    def test_one_file_past_the_member_bound(self, monkeypatch):
        """An unpack holds one member whole, so one member is what is bounded -
        however small the archive that carries it."""
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_MEMBER_BYTES", 10)
        with pytest.raises(BadRequestError, match="too large to unpack"):
            scan_archive(_zip(("a.txt", b"x" * 11)), "zip")

    def test_an_empty_zip_holds_nothing(self):
        assert scan_archive(_zip(), "zip") == []

    def test_too_many_entries_in_a_zip(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_ENTRIES", 2)
        with pytest.raises(BadRequestError, match="too many files"):
            scan_archive(_zip(("a", b"1"), ("b", b"2"), ("c", b"3")), "zip")

    def test_a_folder_named_over_and_over_still_counts(self, monkeypatch):
        """A tar may repeat one folder's header as often as it likes; each is a
        header read, and the entry bound is what limits how many get read."""
        folder = tarfile.TarInfo("a")
        folder.type = tarfile.DIRTYPE
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_ENTRIES", 5)

        with pytest.raises(BadRequestError, match="too many files"):
            scan_archive(_tar(*[folder] * 6), "targz")

    def test_too_many_entries_in_a_tar(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_ENTRIES", 2)
        with pytest.raises(BadRequestError, match="too many files"):
            scan_archive(_tar(("a", b"1"), ("b", b"2"), ("c", b"3")), "targz")

    @pytest.mark.parametrize(
        ("data", "fmt", "named"),
        [
            (b"PK\x03\x04 not really", "zip", ".zip"),
            (b"\x1f\x8b broken gzip", "targz", ".tar.gz"),
            (b"\x1f\x8b" + _zip(("a", b"1"))[2:], "targz", ".tar.gz"),
        ],
    )
    def test_a_file_that_is_not_the_archive_it_claims(self, data, fmt, named):
        with pytest.raises(BadRequestError, match=f"could not be read as a \\{named}"):
            scan_archive(data, fmt)

    def test_a_gz_that_is_not_a_tar(self):
        import gzip

        with pytest.raises(BadRequestError, match="could not be read"):
            scan_archive(gzip.compress(b"just text, not a tar " * 40), "targz")


@pytest.mark.security
class TestMemberNames:
    def test_the_root_is_nothing(self):
        assert safe_member_path("./") is None
        assert safe_member_path("a//./b") == "a/b"


class TestUnpackingIntoAWorkspace:
    async def test_the_tree_lands_under_the_folder(self):
        document = CappedStateBackend(max_bytes=1024 * 1024)
        data = _zip(*REPO, ("repo/empty/", b""), ("repo/src/", b""))

        await unpack_into(document_workspace(document), "uploads/ab12cd34-repo", data, "zip")

        assert document.read_bytes("uploads/ab12cd34-repo/repo/src/app.py") == b"print('hi')\n"
        assert document.exists("uploads/ab12cd34-repo/repo/empty")

    async def test_a_refused_write_leaves_no_partial_tree(self):
        # A partial tree would read, to the next turn's `exists`, as unpacked.
        document = CappedStateBackend(max_bytes=40)
        data = _zip(("a.txt", b"x" * 30), ("b.txt", b"y" * 30))

        with pytest.raises(OSError):
            await unpack_into(document_workspace(document), "uploads/x-repo", data, "zip")

        assert not document.exists("uploads/x-repo/a.txt")
        assert not document.exists("uploads/x-repo")

    async def test_a_cleanup_that_fails_too_keeps_the_first_error(self):
        workspace = ShellFailing(document_workspace())
        workspace.remove = AsyncMock(side_effect=WorkspaceError("gone"))

        with pytest.raises(WorkspaceError, match="shell filesystem write failed"):
            await unpack_into(workspace, "uploads/x-repo", _zip(("a.txt", b"1")), "zip")

    async def test_a_stopped_turn_leaves_no_partial_tree(self):
        """Stop during an unpack is the commonest way out of one, and is a
        cancellation rather than an error - the clean-up has to run for it too."""
        document = CappedStateBackend(max_bytes=1024 * 1024)
        workspace = document_workspace(document)
        written = anyio.Event()
        original = workspace.write_bytes

        async def slow_write(path: str, data: bytes) -> None:
            await original(path, data)
            written.set()
            await anyio.sleep(10)

        workspace.write_bytes = slow_write
        data = _zip(("a.txt", b"1"), ("b.txt", b"2"))

        async with anyio.create_task_group() as group:
            group.start_soon(unpack_into, workspace, "uploads/x-repo", data, "zip")
            await written.wait()
            group.cancel_scope.cancel()

        assert not document.exists("uploads/x-repo/a.txt")
        assert not document.exists("uploads/x-repo")

    async def test_a_stop_while_a_member_inflates_still_removes_the_tree(self, monkeypatch):
        """The read runs on the pool, and most of an unpack is spent there. A stop
        that lands then must wait for the read, not close a reader still running
        on another thread - which raised in place of the stop and skipped the
        clean-up."""
        real = workspace_archive._members
        reading = threading.Event()
        release = threading.Event()

        def slow(data: bytes, fmt: str, *, keep: bool):
            for index, member in enumerate(real(data, fmt, keep=keep)):
                if keep and index == 1:
                    reading.set()
                    release.wait(5)
                yield member

        monkeypatch.setattr(workspace_archive, "_members", slow)
        document = CappedStateBackend(max_bytes=1024 * 1024)
        task = asyncio.ensure_future(
            unpack_into(
                document_workspace(document),
                "uploads/x-repo",
                _zip(("a.txt", b"1"), ("b.txt", b"2")),
                "zip",
            )
        )
        await anyio.to_thread.run_sync(reading.wait, 5)
        task.cancel()
        threading.Timer(0.05, release.set).start()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert not document.exists("uploads/x-repo")

    async def test_a_second_cancel_does_not_interrupt_the_clean_up(self):
        document = CappedStateBackend(max_bytes=1024 * 1024)
        workspace = document_workspace(document)
        removing = asyncio.Event()
        written = asyncio.Event()
        original_remove = workspace.remove
        original_write = workspace.write_bytes

        async def slow_remove(path: str) -> None:
            removing.set()
            await asyncio.sleep(0.05)
            await original_remove(path)

        async def stuck_write(path: str, data: bytes) -> None:
            await original_write(path, data)
            written.set()
            await asyncio.sleep(10)

        workspace.remove = slow_remove
        workspace.write_bytes = stuck_write
        task = asyncio.ensure_future(
            unpack_into(workspace, "uploads/x-repo", _zip(("a.txt", b"1")), "zip")
        )
        await written.wait()
        task.cancel()
        await removing.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert not document.exists("uploads/x-repo")

    async def test_a_stop_during_the_clean_up_of_a_failed_write_is_still_a_stop(self):
        """The write's error is what the caller handles and carries on from, so
        raising it in place of an absorbed stop would let the turn go on."""
        document = CappedStateBackend(max_bytes=1024 * 1024)
        workspace = document_workspace(document)
        removing = asyncio.Event()
        original_remove = workspace.remove

        async def failing_write(path: str, data: bytes) -> None:
            raise OSError("the host went away")

        async def slow_remove(path: str) -> None:
            removing.set()
            await asyncio.sleep(0.05)
            await original_remove(path)

        workspace.write_bytes = failing_write
        workspace.remove = slow_remove
        task = asyncio.ensure_future(
            unpack_into(workspace, "uploads/x-repo", _zip(("a.txt", b"1")), "zip")
        )
        await removing.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert not document.exists("uploads/x-repo")

    async def test_a_cancelled_scope_does_not_spin_the_clean_up(self, monkeypatch):
        """An anyio scope delivers its cancellation again at every await; the
        clean-up waits once rather than once per delivery."""
        waits = 0
        real_wait = asyncio.wait

        async def counting_wait(*args, **kwargs):
            nonlocal waits
            waits += 1
            return await real_wait(*args, **kwargs)

        monkeypatch.setattr(workspace_archive.asyncio, "wait", counting_wait)
        document = CappedStateBackend(max_bytes=1024 * 1024)
        workspace = document_workspace(document)
        written = asyncio.Event()
        original_write = workspace.write_bytes
        original_remove = workspace.remove

        async def stuck_write(path: str, data: bytes) -> None:
            await original_write(path, data)
            written.set()
            await asyncio.sleep(10)

        async def slow_remove(path: str) -> None:
            await asyncio.sleep(0.1)
            await original_remove(path)

        workspace.write_bytes = stuck_write
        workspace.remove = slow_remove

        async with anyio.create_task_group() as group:
            group.start_soon(unpack_into, workspace, "uploads/x-repo", _zip(("a.txt", b"1")), "zip")
            await written.wait()
            group.cancel_scope.cancel()

        assert not document.exists("uploads/x-repo")
        assert waits <= 3

    async def test_an_unsafe_archive_writes_nothing_at_all(self):
        document = CappedStateBackend(max_bytes=1024 * 1024)

        with pytest.raises(BadRequestError):
            await unpack_into(
                document_workspace(document),
                "uploads/x-repo",
                _zip(("a.txt", b"1"), ("../b.txt", b"2")),
                "zip",
            )

        assert not document.exists("uploads/x-repo")
        assert not document.exists("uploads/x-repo/a.txt")


class TestZippingAFolder:
    def test_a_folder_climbing_out_is_refused(self):
        with pytest.raises(BadRequestError):
            zip_folder("uploads/../../etc")

    def test_backend_spellings_are_one_folder(self):
        assert zip_folder("./uploads/") == "uploads"
        assert zip_folder("/uploads") == "uploads"
        assert zip_folder(".") == ""

    @pytest.mark.parametrize(
        ("spelled", "folder"),
        [("a//b", "a/b"), ("a/./b", "a/b"), ("./a//b/", "a/b"), ("a/.", "a"), ("/./a/b", "a/b")],
    )
    def test_a_folder_is_spelled_by_its_segments_as_the_host_spells_it(self, spelled, folder):
        """The host canonicalises by segments; a folder matched on any other spelling
        matched only itself, and zipped empty with its files left behind."""
        assert zip_folder(spelled) == folder

    def test_only_the_folder_is_picked_under_its_own_name(self):
        picked, name = zip_members(
            [
                ("/uploads/repo/a.py", 3, False),
                ("./uploads/repo/sub/b.py", None, False),
                ("/other.txt", 1, False),
            ],
            "uploads/repo",
        )

        assert name == "repo.zip"
        assert picked == [
            ("uploads/repo", "repo/"),
            ("/uploads/repo/a.py", "repo/a.py"),
            ("./uploads/repo/sub/b.py", "repo/sub/b.py"),
        ]

    def test_a_folder_s_folders_are_entries_of_their_own(self):
        """An empty folder has no file to imply it, so it is lost unless named."""
        picked, _name = zip_members(
            [
                ("/repo", 0, True),
                ("/repo/empty", 0, True),
                ("/repo/src", 0, True),
                ("/repo/src/a.py", 1, False),
            ],
            "repo",
        )

        assert picked == [
            ("repo", "repo/"),
            ("/repo/empty", "repo/empty/"),
            ("/repo/src", "repo/src/"),
            ("/repo/src/a.py", "repo/src/a.py"),
        ]

    def test_an_empty_folder_is_a_zip_of_that_folder(self):
        picked, name = zip_members([("/repo/empty", 0, True)], "repo/empty")

        assert (picked, name) == ([("repo/empty", "empty/")], "empty.zip")

    @pytest.mark.parametrize(
        ("entries", "folder"),
        [
            ([("/repo/a.py", 1, False)], "other"),
            ([("/repo", 1, False)], "repo"),
            ([("/", 0, True), (".", 0, True)], ""),
            ([], ""),
        ],
    )
    def test_a_folder_that_is_not_there_is_not_found(self, entries, folder):
        with pytest.raises(NotFoundError):
            zip_members(entries, folder)

    async def test_a_zip_at_the_entry_bound_can_be_attached_again(self, monkeypatch):
        """The top folder is a member too, and the attaching side counts it."""
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_ENTRIES", 3)
        picked, _name = zip_members([("a/x", 1, False), ("a/y", 1, False)], "a")

        data = b"".join([chunk async for chunk in stream_zip(picked, AsyncMock(return_value=b"1"))])

        assert len(scan_archive(data, "zip")) == 3
        with pytest.raises(ExportTooLargeError):
            zip_members([("a/x", 1, False), ("a/y", 1, False), ("a/z", 1, False)], "a")

    @pytest.mark.security
    def test_the_top_folder_s_own_name_is_encoded(self):
        picked, name = zip_members([("a\\..\\evil/x", 1, False)], "a\\..\\evil")

        assert picked == [
            ("a\\..\\evil", "a%5C..%5Cevil/"),
            ("a\\..\\evil/x", "a%5C..%5Cevil/x"),
        ]
        assert name == "a%5C..%5Cevil.zip"

    def test_folders_count_against_the_entry_bound(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_ENTRIES", 1)

        with pytest.raises(ExportTooLargeError):
            zip_members([("a", 0, True), ("a/b", 0, True)], "")

    @pytest.mark.security
    def test_a_name_an_unpacker_would_split_is_encoded(self):
        """A POSIX name may hold a backslash, which Windows reads as a separator:
        `..\\..\\x` would land outside the folder the zip was saved into."""
        picked, _name = zip_members([("/..\\..\\payload", 1, False), ("/50%\nnew", 1, False)], "")

        assert picked[1:] == [
            ("/..\\..\\payload", "workspace/..%5C..%5Cpayload"),
            ("/50%\nnew", "workspace/50%25%0Anew"),
        ]

    def test_the_whole_workspace(self):
        picked, name = zip_members([("/a.txt", 1, False)], "")

        assert (picked, name) == (
            [("", "workspace/"), ("/a.txt", "workspace/a.txt")],
            "workspace.zip",
        )

    @pytest.mark.parametrize(
        ("setting", "value"),
        [("WORKSPACE_ARCHIVE_MAX_ENTRIES", 1), ("WORKSPACE_ARCHIVE_MAX_BYTES", 5)],
    )
    def test_a_folder_past_the_bounds_is_refused(self, monkeypatch, setting, value):
        monkeypatch.setattr(settings, setting, value)

        with pytest.raises(ExportTooLargeError):
            zip_members([("a", 3, False), ("b", 3, False)], "")

    async def test_the_stream_is_a_zip_of_the_same_tree(self):
        files = {"/repo/a.py": b"a" * 1000, "/repo/sub/b.py": b"b"}

        async def read(path: str) -> bytes:
            return files[path]

        chunks = [
            chunk
            async for chunk in stream_zip(
                [("/repo/a.py", "repo/a.py"), ("/repo/sub/b.py", "repo/sub/b.py")], read
            )
        ]

        assert len([chunk for chunk in chunks if chunk]) >= 2
        with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
            assert {name: archive.read(name) for name in archive.namelist()} == {
                "repo/a.py": b"a" * 1000,
                "repo/sub/b.py": b"b",
            }

    async def test_a_folder_is_written_as_a_folder_and_never_read(self):
        read = AsyncMock(return_value=b"a")

        chunks = [
            chunk
            async for chunk in stream_zip(
                [("repo", "repo/"), ("/repo/empty", "repo/empty/"), ("/repo/a", "repo/a")], read
            )
        ]

        with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
            assert archive.namelist() == ["repo/", "repo/empty/", "repo/a"]
            assert archive.getinfo("repo/empty/").is_dir()
            assert archive.read("repo/a") == b"a"
        read.assert_awaited_once_with("/repo/a")

    async def test_a_file_that_cannot_be_read_is_named_rather_than_breaking_the_zip(self):
        async def read(path: str) -> bytes:
            if path == "/repo/big.bin":
                raise BadRequestError(message="File is 9437184 bytes, over the read limit")
            if path == "/repo/gone.txt":
                raise NotFoundError(message="No such file")
            return b"kept"

        chunks = [
            chunk
            async for chunk in stream_zip(
                [
                    ("/repo/a.py", "repo/a.py"),
                    ("/repo/big.bin", "repo/big.bin"),
                    ("/repo/gone.txt", "repo/gone.txt"),
                ],
                read,
            )
        ]

        with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
            assert archive.read("repo/a.py") == b"kept"
            note = archive.read(f"repo/{NOT_INCLUDED}").decode()
        assert "repo/big.bin: File is 9437184 bytes, over the read limit" in note
        assert "repo/gone.txt: No such file" in note

    async def test_the_note_never_shares_a_name_with_a_file_of_the_folder(self):
        async def read(path: str) -> bytes:
            if path == "/repo/gone":
                raise NotFoundError(message="No such file")
            return b"theirs"

        chunks = [
            chunk
            async for chunk in stream_zip(
                [("/repo/NOT-INCLUDED.txt", "repo/NOT-INCLUDED.txt"), ("/repo/gone", "repo/gone")],
                read,
            )
        ]

        with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
            assert archive.read("repo/NOT-INCLUDED.txt") == b"theirs"
            assert b"repo/gone: No such file" in archive.read("repo/_NOT-INCLUDED.txt")

    @pytest.mark.security
    async def test_a_file_that_grew_past_the_bound_stops_the_stream(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_BYTES", 4)

        async def read(path: str) -> bytes:
            return b"12345"

        with pytest.raises(BadRequestError, match="grew past"):
            async for _chunk in stream_zip([("/a", "a")], read):
                pass
