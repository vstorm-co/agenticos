"""Bounded archive transport; no extraction, provider calls or executable imports."""

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from io import SEEK_END
from stat import S_IFLNK, S_IFMT
from typing import BinaryIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile
from zlib import error as ZlibError

from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.schemas.resource_bundle import BundleAsset, ResourceBundle


@dataclass(frozen=True, slots=True)
class BundleLimits:
    compressed_bytes: int = 512 * 1024 * 1024
    expanded_bytes: int = 2 * 1024 * 1024 * 1024
    manifest_bytes: int = 4 * 1024 * 1024
    entry_bytes: int = 512 * 1024 * 1024
    entries: int = 100_001


def _refuse(message: str) -> BadRequestError:
    return BadRequestError(message=message, details={"field": "bundle"})


class BundleArchive:
    """A validated index; streamed assets remain untrusted until their digest passes.

    The owner must stage yielded bytes and publish them only after the iterator
    completes. Callers must keep the surrounding `open_bundle` context open.
    """

    def __init__(self, archive: ZipFile, manifest: ResourceBundle) -> None:
        self.archive = archive
        self.manifest = manifest

    def asset_chunks(self, asset: BundleAsset) -> Iterator[bytes]:
        if asset not in self.manifest.assets:
            raise _refuse("This asset is not declared by the bundle")
        digest = sha256()
        length = 0
        try:
            with self.archive.open(asset.archive_path) as member:
                while chunk := member.read(64 * 1024):
                    length += len(chunk)
                    digest.update(chunk)
                    yield chunk
        except (BadZipFile, EOFError, ZlibError) as exc:
            raise _refuse("An asset is corrupt or incomplete") from exc
        if length != asset.size_bytes or digest.hexdigest() != asset.sha256:
            raise _refuse("An asset does not match its declared size or digest")


def _manifest(archive: ZipFile, limits: BundleLimits) -> ResourceBundle:
    members = archive.infolist()
    if len(members) > limits.entries:
        raise _refuse("This bundle contains too many archive entries")
    by_name = {member.filename: member for member in members}
    if len(by_name) != len(members):
        raise _refuse("Archive member names must be unique")
    if "manifest.json" not in by_name:
        raise _refuse("A bundle must contain manifest.json")
    expanded = 0
    for member in members:
        if (
            member.is_dir()
            or member.flag_bits & 1
            or S_IFMT(member.external_attr >> 16) == S_IFLNK
            or member.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
        ):
            raise _refuse("Directories, links, encrypted or unsupported entries are not allowed")
        if member.file_size > limits.entry_bytes:
            raise _refuse("An archive entry exceeds the configured size limit")
        expanded += member.file_size
    if expanded > limits.expanded_bytes:
        raise _refuse("This bundle exceeds the expanded size limit")
    if by_name["manifest.json"].file_size > limits.manifest_bytes:
        raise _refuse("The bundle manifest exceeds the size limit")
    try:
        with archive.open("manifest.json") as source:
            data = source.read(limits.manifest_bytes + 1)
        manifest = ResourceBundle.model_validate_json(data)
    except ValidationError as exc:
        raise _refuse("The bundle manifest does not match a supported format") from exc
    expected = {"manifest.json", *(asset.archive_path for asset in manifest.assets)}
    if expected != set(by_name):
        raise _refuse("The archive must contain exactly its manifest and declared assets")
    for asset in manifest.assets:
        if by_name[asset.archive_path].file_size != asset.size_bytes:
            raise _refuse("An archive asset has a different size from its declaration")
    return manifest


@contextmanager
def open_bundle(
    stream: BinaryIO, *, limits: BundleLimits = BundleLimits()
) -> Generator[BundleArchive]:
    """Validate a seekable upload without extracting paths or closing the caller's file."""
    stream.seek(0, SEEK_END)
    if stream.tell() > limits.compressed_bytes:
        raise _refuse("This bundle exceeds the compressed size limit")
    stream.seek(0)
    try:
        archive = ZipFile(stream)
    except (BadZipFile, EOFError) as exc:
        raise _refuse("This is not a complete, supported bundle archive") from exc
    with archive:
        try:
            manifest = _manifest(archive, limits)
        except (BadZipFile, EOFError, ZlibError) as exc:
            raise _refuse("The bundle manifest is corrupt or incomplete") from exc
        yield BundleArchive(archive, manifest)
