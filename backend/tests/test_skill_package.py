"""Skill packages are bounded inert inputs; resources retain their original bytes."""

import hashlib
import stat
from io import BytesIO
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from app.core.exceptions import BadRequestError
from app.services import skill_package
from app.services.skill_package import package_path, read_package_files, read_package_zip

pytestmark = pytest.mark.security
BODY = b"---\nname: proposal-builder\ndescription: Generate proposals from a template.\n---\n\nUse assets/template.xlsx.\n"
ASSET = b"PK\x03\x04binary\x00\xfftemplate"
FILES = [
    ("SKILL.md", BODY),
    ("scripts/build.py", b"raise RuntimeError('must not execute')\n"),
    ("assets/template.xlsx", ASSET),
]


def zipped(files: list[tuple[str, bytes]], compression: int = ZIP_DEFLATED) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=compression) as archive:
        for name, raw in files:
            archive.writestr(name, raw)
    return buffer.getvalue()


def test_zip_directory_and_enclosing_folder_have_identical_content() -> None:
    package = read_package_files(FILES)
    assert read_package_zip(zipped(FILES)) == package
    assert read_package_files([("proposal-builder/" + name, raw) for name, raw in FILES]) == package
    assert package.resources[0].raw == ASSET
    preview = package.preview()
    assert preview.execution == "none"
    assert preview.total_bytes == sum(len(raw) for _, raw in FILES)
    assert preview.files[0].encoding == "base64"
    assert preview.files[0].sha256 == hashlib.sha256(ASSET).hexdigest()
    assert not hasattr(preview.files[0], "content")


@pytest.mark.parametrize(
    "path",
    [
        "/root/x",
        "../x",
        "a/../../x",
        "a/./x",
        "a//x",
        "a\\x",
        "C:/x",
        "x\x00y",
        ".git/config",
        ".agenticos/private",
        "",
    ],
)
def test_unsafe_paths_are_refused(path: str) -> None:
    with pytest.raises(BadRequestError):
        package_path(path)


@pytest.mark.parametrize(
    "files",
    [
        [],
        [("readme.md", b"no root")],
        [("a/SKILL.md", BODY), ("b/SKILL.md", BODY)],
        [("a/SKILL.md", BODY), ("outside.txt", b"outside")],
        [("SKILL.md", BODY), ("Assets/x", ASSET), ("assets/X", b"collision")],
        [("SKILL.md", BODY), ("scripts", b"file"), ("scripts/build.py", b"conflict")],
    ],
)
def test_ambiguous_roots_and_path_collisions_are_refused(files: list[tuple[str, bytes]]) -> None:
    with pytest.raises(BadRequestError):
        read_package_files(files)


@pytest.mark.parametrize(
    "body",
    [
        b"no frontmatter",
        b"---\nname: proposal-builder\n---\nbody",
        b"---\nname: bad name\ndescription: A skill.\n---\nbody",
        b"---\n[bad\n---\nbody",
        b"\xff",
        BODY + b"\0",
    ],
)
def test_manifest_validation_happens_before_applying(body: bytes) -> None:
    with pytest.raises(BadRequestError):
        read_package_files([("SKILL.md", body)])


def test_nested_manifest_is_a_resource_and_long_paths_are_refused() -> None:
    package = read_package_files([*FILES, ("references/child/SKILL.md", BODY)])
    assert "references/child/SKILL.md" in {file.name for file in package.resources}
    with pytest.raises(BadRequestError, match="128"):
        read_package_files([("SKILL.md", BODY), ("x" * 129, b"x")])


def test_archive_symlinks_and_unsupported_compression_are_refused() -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", BODY)
        link = ZipInfo("references/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "../../outside")
    with pytest.raises(BadRequestError, match="Symlinks"):
        read_package_zip(buffer.getvalue())
    with pytest.raises(BadRequestError, match="unsupported"):
        read_package_zip(zipped(FILES, ZIP_BZIP2))


def test_archive_duplicates_corruption_and_directory_entries() -> None:
    with pytest.warns(UserWarning, match="Duplicate"):
        duplicate = zipped([("SKILL.md", BODY), ("SKILL.md", BODY)])
    with pytest.raises(BadRequestError, match="unique"):
        read_package_zip(duplicate)
    for raw in (b"not a zip", zipped(FILES)[:-16]):
        with pytest.raises(BadRequestError, match="ZIP archive"):
            read_package_zip(raw)
    assert read_package_zip(zipped([("assets/", b""), *FILES])) == read_package_files(FILES)


def test_count_and_byte_limits_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_package, "MAX_SKILL_PACKAGE_FILES", 2)
    with pytest.raises(BadRequestError, match="file-count"):
        read_package_files(FILES)
    with pytest.raises(BadRequestError, match="too many"):
        read_package_zip(zipped(FILES))
    monkeypatch.setattr(skill_package, "MAX_SKILL_PACKAGE_FILES", 10)
    monkeypatch.setattr(skill_package, "MAX_SKILL_FILE_BYTES", len(BODY) - 1)
    with pytest.raises(BadRequestError, match="file limit"):
        read_package_files(FILES)
    with pytest.raises(BadRequestError, match="file limit"):
        read_package_zip(zipped(FILES))
    monkeypatch.setattr(skill_package, "MAX_SKILL_FILE_BYTES", 1000)
    monkeypatch.setattr(skill_package, "MAX_SKILL_PACKAGE_BYTES", len(BODY))
    with pytest.raises(BadRequestError, match="32 MiB"):
        read_package_files(FILES)
    with pytest.raises(BadRequestError, match="compressed"):
        read_package_zip(zipped(FILES))


@pytest.mark.parametrize(
    "header",
    [
        "name: proposal-builder\nname: duplicate\ndescription: A skill.",
        "name: proposal-builder\ndescription: &text A skill.\nmetadata: *text",
        "name: proposal-builder\ndescription: A skill.\nmetadata: !!python/object/apply:os.system [echo bad]",
        "name: proposal-builder\ndescription: A skill.\nmetadata: {x: 1, x: 2}",
    ],
)
def test_duplicate_alias_and_unsafe_yaml_frontmatter_are_refused(header: str) -> None:
    with pytest.raises(BadRequestError):
        read_package_files([("SKILL.md", ("---\n" + header + "\n---\nInert body.").encode())])


def test_extra_frontmatter_remains_explicit_inert_metadata() -> None:
    body = b"---\nname: proposal-builder\ndescription: A skill.\nlicense: MIT\nallowed-tools: [execute]\nmetadata: {revision: 2}\n---\nBody"
    package = read_package_files([("SKILL.md", body)])
    assert package.preview().manifest_metadata == {
        "license": "MIT",
        "allowed-tools": ["execute"],
        "metadata": {"revision": 2},
    }


@pytest.mark.parametrize(
    "value",
    [
        "{nested: .nan}",
        "{nested: .inf}",
        "{nested: -.inf}",
        "{nested: 2026-11-27}",
        "{nested: !!binary eA==}",
        "{1: value}",
    ],
)
def test_frontmatter_refuses_non_json_values_before_storage(value: str) -> None:
    raw = (
        f"---\nname: proposal-builder\ndescription: A skill.\nmetadata: {value}\n---\nBody".encode()
    )
    with pytest.raises(BadRequestError):
        read_package_files([("SKILL.md", raw)])


def test_nested_skill_document_is_an_inert_resource_when_root_is_explicit() -> None:
    package = read_package_files(
        [("SKILL.md", BODY), ("references/SKILL.md", b"inert nested documentation")]
    )
    assert package.resources[0].name == "references/SKILL.md"
    assert package.resources[0].raw == b"inert nested documentation"


@pytest.mark.anyio
async def test_package_service_refuses_creation_without_edit_permission() -> None:
    from uuid import uuid4

    from app.core.exceptions import AuthorizationError
    from app.core.permissions import AuthContext, OrgRoleName
    from app.services.skill_package import SkillPackageService

    viewer = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.VIEWER)
    with pytest.raises(AuthorizationError):
        await SkillPackageService._parse(viewer, FILES, archive=False)


@pytest.mark.anyio
async def test_package_service_explicit_zip_format_and_single_archive() -> None:
    from uuid import uuid4

    from app.core.permissions import AuthContext, OrgRoleName
    from app.services.skill_package import SkillPackageService

    owner = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    package = await SkillPackageService._parse(
        owner, [("package.zip", zipped(FILES))], archive=True
    )
    assert package.resources[0].raw == ASSET
    with pytest.raises(BadRequestError, match="exactly one"):
        await SkillPackageService._parse(owner, FILES, archive=True)


def test_root_markdown_indentation_and_trailing_newlines_are_not_normalized() -> None:
    instructions = "\n    first indented code line\n    next line\n\n"
    package = read_package_files(
        [
            (
                "SKILL.md",
                ("---\nname: proposal-builder\ndescription: A skill.\n---" + instructions).encode(),
            )
        ]
    )
    assert package.metadata.content == instructions
    assert package.preview().content == instructions
