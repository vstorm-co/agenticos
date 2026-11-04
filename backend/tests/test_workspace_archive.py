"""Archives into a workspace and out of one (#2479).

The refusals are the point. An archive is the classic way to write outside a
directory - a `../` member, an absolute path, a link a later member writes
through, a device node - and the classic way to spend a server's memory, with a
few kilobytes that inflate to gigabytes. Each is refused before one byte lands.
"""

import io
import stat
import tarfile
import zipfile
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.core.config import settings
from app.core.exceptions import BadRequestError, ExportTooLargeError
from app.services.workspace_archive import (
    ArchiveMember,
    archive_format,
    manifest,
    read_archive,
    safe_member_path,
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


REPO = (
    ("repo/README.md", b"# repo\n"),
    ("repo/src/app.py", b"print('hi')\n"),
    ("repo/tests/test_app.py", b"def test_it():\n    assert True\n"),
)


class TestTheNamesAnArchiveCarries:
    def test_zip_and_both_tar_spellings_are_archives(self):
        assert archive_format("Repo.ZIP") == "zip"
        assert archive_format("repo.tar.gz") == "targz"
        assert archive_format("repo.tgz") == "targz"
        assert archive_format("notes.gz") is None

    def test_the_folder_is_named_after_the_archive(self):
        assert unpacked_name("repo.tar.gz") == "repo"
        assert unpacked_name("repo.zip") == "repo"
        # A name that is only the suffix keeps it rather than becoming nothing.
        assert unpacked_name(".zip") == ".zip"
        assert unpacked_name("notes.txt") == "notes.txt"


class TestASafeArchiveUnpacksToTheSameTree:
    def test_a_zip(self):
        members = read_archive(_zip(*REPO, ("repo/empty/", b"")), "zip")

        files = {member.path: member.data for member in members if not member.is_dir}
        assert files == dict(REPO)
        assert ArchiveMember(path="repo/empty", is_dir=True) in members

    def test_a_tar_gz(self):
        folder = tarfile.TarInfo("./repo/docs")
        folder.type = tarfile.DIRTYPE
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        members = read_archive(_tar(root, folder, folder, *REPO), "targz")

        files = {member.path: member.data for member in members if not member.is_dir}
        assert files == dict(REPO)
        # The root entry `.` is not a folder of its own, and a folder named twice is one.
        assert [member.path for member in members if member.is_dir] == ["repo/docs"]

    def test_the_manifest_opens_on_a_count_and_lists_the_tree(self):
        text = manifest(read_archive(_zip(*REPO, ("repo/empty/", b"")), "zip"))

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
            read_archive(_zip((name, b"x")), "zip")

    def test_a_tar_member_that_climbs_out(self):
        with pytest.raises(BadRequestError, match=r"\.\."):
            read_archive(_tar(("../../etc/cron.d/x", b"x")), "targz")

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
            read_archive(_tar(member), "targz")

    def test_a_symlink_in_a_zip(self):
        with pytest.raises(BadRequestError, match="link or a special file"):
            read_archive(_zip(("repo/link", b"/etc/passwd"), mode=stat.S_IFLNK | 0o777), "zip")

    def test_a_zip_entry_marked_a_folder_by_its_mode_is_a_folder(self):
        members = read_archive(_zip(("repo/dir", b""), mode=stat.S_IFDIR | 0o755), "zip")

        assert members == [ArchiveMember(path="repo/dir", is_dir=True)]

    def test_an_encrypted_zip(self):
        with pytest.raises(BadRequestError, match="encrypted"):
            read_archive(_zip(("a.txt", b"x"), encrypted=True), "zip")

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
            read_archive(_zip(*members), "zip")

    def test_a_folder_named_where_a_file_is(self):
        with pytest.raises(BadRequestError, match="same path twice"):
            read_archive(_zip(("a", b"1"), ("a/", b"")), "zip")

    def test_a_file_with_no_name(self):
        with pytest.raises(BadRequestError, match="no name"):
            read_archive(_tar(("./", b"x")), "targz")


@pytest.mark.security
class TestAnArchiveThatSpendsTheServerIsRefused:
    def test_a_zip_bomb_by_ratio(self):
        with pytest.raises(BadRequestError, match="decompression bomb"):
            read_archive(_zip(("zeros", b"\0" * (4 * 1024 * 1024))), "zip")

    def test_a_tar_gz_bomb_stops_inflating_at_the_bound(self, monkeypatch):
        # The members' own count never gets to see it: the stream is bounded first.
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_RATIO", 1)
        with pytest.raises(BadRequestError, match="too large once unpacked"):
            read_archive(_tar(("zeros", b"\0" * (4 * 1024 * 1024))), "targz")

    def test_past_the_byte_limit(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_BYTES", 10)
        with pytest.raises(BadRequestError, match="too large once unpacked"):
            read_archive(_zip(("a.txt", b"x" * 11)), "zip")

    def test_too_many_entries_in_a_zip(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_ENTRIES", 2)
        with pytest.raises(BadRequestError, match="too many files"):
            read_archive(_zip(("a", b"1"), ("b", b"2"), ("c", b"3")), "zip")

    def test_too_many_entries_in_a_tar(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_ENTRIES", 2)
        with pytest.raises(BadRequestError, match="too many files"):
            read_archive(_tar(("a", b"1"), ("b", b"2"), ("c", b"3")), "targz")

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
            read_archive(data, fmt)

    def test_a_gz_that_is_not_a_tar(self):
        import gzip

        with pytest.raises(BadRequestError, match="could not be read"):
            read_archive(gzip.compress(b"just text, not a tar " * 40), "targz")


@pytest.mark.security
class TestMemberNames:
    def test_the_root_is_nothing(self):
        assert safe_member_path("./") is None
        assert safe_member_path("a//./b") == "a/b"


class TestUnpackingIntoAWorkspace:
    async def test_the_tree_lands_under_the_folder(self):
        document = CappedStateBackend(max_bytes=1024 * 1024)
        members = read_archive(_zip(*REPO, ("repo/empty/", b"")), "zip")

        await unpack_into(document_workspace(document), "uploads/ab12cd34-repo", members)

        assert document.read_bytes("uploads/ab12cd34-repo/repo/src/app.py") == b"print('hi')\n"
        assert document.exists("uploads/ab12cd34-repo/repo/empty")

    async def test_a_refused_write_leaves_no_partial_tree(self):
        # A partial tree would read, to the next turn's `exists`, as unpacked.
        document = CappedStateBackend(max_bytes=40)
        members = read_archive(_zip(("a.txt", b"x" * 30), ("b.txt", b"y" * 30)), "zip")

        with pytest.raises(OSError):
            await unpack_into(document_workspace(document), "uploads/x-repo", members)

        assert not document.exists("uploads/x-repo/a.txt")
        assert not document.exists("uploads/x-repo")

    async def test_a_cleanup_that_fails_too_keeps_the_first_error(self):
        workspace = ShellFailing(document_workspace())
        workspace.remove = AsyncMock(side_effect=WorkspaceError("gone"))

        with pytest.raises(WorkspaceError, match="shell filesystem write failed"):
            await unpack_into(workspace, "uploads/x-repo", [ArchiveMember("a.txt", b"1")])


class TestZippingAFolder:
    def test_a_folder_climbing_out_is_refused(self):
        with pytest.raises(BadRequestError):
            zip_folder("uploads/../../etc")

    def test_backend_spellings_are_one_folder(self):
        assert zip_folder("./uploads/") == "uploads"
        assert zip_folder("/uploads") == "uploads"

    def test_only_the_folder_is_picked_under_its_own_name(self):
        picked, name = zip_members(
            [("/uploads/repo/a.py", 3), ("./uploads/repo/sub/b.py", None), ("/other.txt", 1)],
            "uploads/repo",
        )

        assert name == "repo.zip"
        assert picked == [
            ("/uploads/repo/a.py", "repo/a.py"),
            ("./uploads/repo/sub/b.py", "repo/sub/b.py"),
        ]

    def test_the_whole_workspace(self):
        picked, name = zip_members([("/a.txt", 1)], "")

        assert (picked, name) == ([("/a.txt", "workspace/a.txt")], "workspace.zip")

    @pytest.mark.parametrize(
        ("setting", "value"),
        [("WORKSPACE_ARCHIVE_MAX_ENTRIES", 1), ("WORKSPACE_ARCHIVE_MAX_BYTES", 5)],
    )
    def test_a_folder_past_the_bounds_is_refused(self, monkeypatch, setting, value):
        monkeypatch.setattr(settings, setting, value)

        with pytest.raises(ExportTooLargeError):
            zip_members([("a", 3), ("b", 3)], "")

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

    @pytest.mark.security
    async def test_a_file_that_grew_past_the_bound_stops_the_stream(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKSPACE_ARCHIVE_MAX_BYTES", 4)

        async def read(path: str) -> bytes:
            return b"12345"

        with pytest.raises(BadRequestError, match="grew past"):
            async for _chunk in stream_zip([("/a", "a")], read):
                pass
