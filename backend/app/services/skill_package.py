"""Import bounded standalone skill directories and ZIP files without executing them."""

import hashlib
import json
import secrets
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile
from zlib import error as ZlibError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.blocking import run_blocking
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, Perm
from app.core.skill_files import (
    MAX_SKILL_FILE_BYTES,
    MAX_SKILL_PACKAGE_BYTES,
    MAX_SKILL_PACKAGE_FILES,
    EncodedSkillFile,
    encode_skill_file,
    validate_skill_metadata,
)
from app.db.models.skill_version import SkillVersionSource
from app.schemas.skill import SkillCreate
from app.schemas.skill_package import SkillPackageApplied, SkillPackageFile, SkillPackagePreview
from app.services.skill_library import split_frontmatter


@dataclass(frozen=True, slots=True)
class PackageResource:
    name: str
    raw: bytes
    body: EncodedSkillFile


@dataclass(frozen=True, slots=True)
class SkillPackage:
    metadata: SkillCreate
    resources: tuple[PackageResource, ...]
    fingerprint: str
    total_bytes: int

    def preview(self) -> SkillPackagePreview:
        return SkillPackagePreview(
            name=self.metadata.name,
            description=self.metadata.description,
            category=self.metadata.category,
            content=self.metadata.content,
            manifest_metadata=self.metadata.manifest_metadata,
            fingerprint=self.fingerprint,
            total_bytes=self.total_bytes,
            files=[
                SkillPackageFile(
                    name=item.name,
                    size_bytes=len(item.raw),
                    sha256=hashlib.sha256(item.raw).hexdigest(),
                    encoding=item.body.encoding,
                )
                for item in self.resources
            ],
            max_file_bytes=MAX_SKILL_FILE_BYTES,
            max_package_bytes=MAX_SKILL_PACKAGE_BYTES,
            max_files=MAX_SKILL_PACKAGE_FILES,
        )


def _refuse(message: str) -> BadRequestError:
    return BadRequestError(message=message, details={"field": "package"})


def package_path(raw: str) -> str:
    """A strict relative POSIX path, before any stripping or filesystem operation."""
    if not raw or raw.startswith(("/", "\\")) or "\\" in raw or ":" in raw:
        raise _refuse("Package file paths must be relative POSIX paths")
    parts = raw.removesuffix("/").split("/")
    if any(part in ("", ".", "..") or any(ord(char) < 32 for char in part) for part in parts):
        raise _refuse("Package paths cannot traverse directories or contain control characters")
    if any(part.casefold() in (".git", ".agenticos") for part in parts):
        raise _refuse("Package paths cannot contain repository or platform-internal directories")
    return "/".join(parts)


def read_package_zip(raw: bytes) -> SkillPackage:
    """Read validated members in memory; never extract paths, import code or install packages."""
    if len(raw) > MAX_SKILL_PACKAGE_BYTES:
        raise _refuse("The ZIP exceeds the 32 MiB compressed package limit")
    files: list[tuple[str, bytes]] = []
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > MAX_SKILL_PACKAGE_FILES:
                raise _refuse("The package contains too many files or directories")
            seen: set[str] = set()
            expanded = 0
            for member in members:
                name = package_path(member.filename)
                if name.casefold() in seen:
                    raise _refuse("Package paths must be unique, including letter case")
                seen.add(name.casefold())
                mode = stat.S_IFMT(member.external_attr >> 16)
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise _refuse("Symlinks and special files are not supported in skill packages")
                if member.flag_bits & 1 or member.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    raise _refuse("Encrypted or unsupported ZIP members cannot be imported")
                if member.is_dir():
                    continue
                if member.file_size > MAX_SKILL_FILE_BYTES:
                    raise _refuse("A package file exceeds the 8 MiB file limit")
                expanded += member.file_size
                if expanded > MAX_SKILL_PACKAGE_BYTES:
                    raise _refuse("Expanded package files exceed the 32 MiB limit")
                with archive.open(member) as stream:
                    data = stream.read(MAX_SKILL_FILE_BYTES + 1)
                if len(data) != member.file_size or len(data) > MAX_SKILL_FILE_BYTES:
                    raise _refuse("A package file does not match its declared size")
                files.append((name, data))
    except (BadZipFile, EOFError, UnicodeDecodeError, ZlibError, NotImplementedError) as exc:
        raise _refuse("This is not a complete supported ZIP archive") from exc
    return read_package_files(files)


def read_package_files(files: Sequence[tuple[str, bytes]]) -> SkillPackage:
    """Validate one root SKILL.md and supporting files before any database mutation."""
    if not files or len(files) > MAX_SKILL_PACKAGE_FILES:
        raise _refuse("Choose one skill package within the file-count limit")
    indexed: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0
    for raw_name, raw in files:
        name = package_path(raw_name)
        if name.casefold() in seen:
            raise _refuse("Package paths must be unique, including letter case")
        seen.add(name.casefold())
        if len(raw) > MAX_SKILL_FILE_BYTES:
            raise _refuse("A package file exceeds the 8 MiB file limit")
        total += len(raw)
        if total > MAX_SKILL_PACKAGE_BYTES:
            raise _refuse("Expanded package files exceed the 32 MiB limit")
        indexed[name] = raw
    for name in indexed:
        parts = name.split("/")
        if any("/".join(parts[:index]) in indexed for index in range(1, len(parts))):
            raise _refuse("A package path cannot be both a file and a directory")
    roots = (
        ["SKILL.md"]
        if "SKILL.md" in indexed
        else [name for name in indexed if name.count("/") == 1 and name.endswith("/SKILL.md")]
    )
    if len(roots) != 1:
        raise _refuse(
            "Choose a package with one root SKILL.md, optionally inside one enclosing folder"
        )
    root = roots[0]
    prefix = root.removesuffix("SKILL.md")
    if any(not name.startswith(prefix) for name in indexed):
        raise _refuse("Every package file must be inside the SKILL.md root folder")
    if b"\0" in indexed[root]:
        raise _refuse("SKILL.md must not contain NUL bytes")
    try:
        document = indexed[root].decode("utf-8")
        frontmatter, content = split_frontmatter(document)
        metadata = SkillCreate.model_validate(
            {
                "name": frontmatter.get("name"),
                "description": frontmatter.get("description"),
                "category": frontmatter.get("category"),
                "manifest_metadata": validate_skill_metadata(
                    {
                        key: value
                        for key, value in frontmatter.items()
                        if key not in ("name", "description")
                    }
                ),
                "content": content,
            }
        )
    except ValueError as exc:
        raise _refuse(
            "SKILL.md needs valid UTF-8 instructions and name/description frontmatter"
        ) from exc
    resources = []
    hashes = []
    for full_name, raw in sorted(indexed.items()):
        name = full_name[len(prefix) :]
        if len(name) > 128:
            raise _refuse("A resource path exceeds the 128-character limit")
        hashes.append((name, hashlib.sha256(raw).hexdigest()))
        if full_name != root:
            resources.append(PackageResource(name, raw, encode_skill_file(raw)))
    fingerprint = hashlib.sha256(json.dumps(hashes, separators=(",", ":")).encode()).hexdigest()
    return SkillPackage(metadata, tuple(resources), fingerprint, total)


class SkillPackageService:
    """Preview or create a private skill with its complete first immutable version."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    async def _parse(
        ctx: AuthContext, files: Sequence[tuple[str, bytes]], *, archive: bool
    ) -> SkillPackage:
        if not ctx.has(Perm.SKILLS_EDIT):
            raise AuthorizationError(message="Creating a skill requires skills:edit")
        if archive:
            if len(files) != 1:
                raise _refuse("Choose exactly one ZIP archive")
            return await run_blocking(read_package_zip, files[0][1])
        return await run_blocking(read_package_files, files)

    async def preview(
        self, ctx: AuthContext, files: Sequence[tuple[str, bytes]], *, archive: bool
    ) -> SkillPackagePreview:
        package = await self._parse(ctx, files, archive=archive)
        return package.preview()

    async def apply(
        self,
        ctx: AuthContext,
        files: Sequence[tuple[str, bytes]],
        *,
        archive: bool,
        expected_fingerprint: str,
    ) -> SkillPackageApplied:
        from app.services.skills import SkillService

        package = await self._parse(ctx, files, archive=archive)
        if not secrets.compare_digest(expected_fingerprint, package.fingerprint):
            raise BadRequestError(message="The package changed since its preview; preview it again")
        metadata = package.metadata
        skills = SkillService(self.db)
        skill = await skills.create(
            ctx,
            name=metadata.name,
            description=metadata.description,
            content=metadata.content,
            category=metadata.category,
            manifest_metadata=metadata.manifest_metadata,
            source=None if package.resources else SkillVersionSource.CREATED,
        )
        if package.resources:
            await skills.put_resources(
                ctx,
                skill.id,
                [(file.name, file.raw) for file in package.resources],
                source=SkillVersionSource.CREATED,
            )
        if skill.latest_version_id is None:
            raise RuntimeError("An imported skill must have its complete first version")
        return SkillPackageApplied(
            skill_id=skill.id,
            version_id=skill.latest_version_id,
            name=skill.name,
            files=len(package.resources),
            fingerprint=package.fingerprint,
        )
