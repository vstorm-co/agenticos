"""Multipart package inputs and authenticated lossless binary downloads."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.skill import SkillResourceRead
from app.schemas.skill_package import SkillPackageApplied, SkillPackagePreview
from app.schemas.skill_version import VersionResourceRead

pytestmark = pytest.mark.anyio
SKILL, VERSION, RESOURCE = uuid4(), uuid4(), uuid4()


@pytest.fixture
async def package_client(
    mock_redis: MagicMock,
) -> AsyncIterator[tuple[AsyncClient, MagicMock, MagicMock, MagicMock, AuthContext]]:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    package = MagicMock()
    package.preview = AsyncMock(
        return_value=SkillPackagePreview(
            name="template",
            description="Prepare files.",
            category=None,
            content="Use assets.",
            fingerprint="a" * 64,
            files=[],
            total_bytes=1,
            max_file_bytes=8,
            max_package_bytes=32,
            max_files=1024,
        )
    )
    package.apply = AsyncMock(
        return_value=SkillPackageApplied(
            skill_id=SKILL, version_id=VERSION, name="template", files=1, fingerprint="a" * 64
        )
    )
    skills = MagicMock(
        get_resource=AsyncMock(
            return_value=SkillResourceRead(
                id=RESOURCE,
                name="assets/a b.pdf",
                description=None,
                content="AP+A",
                encoding="base64",
            )
        )
    )
    versions = MagicMock(
        read_resource=AsyncMock(
            return_value=VersionResourceRead(
                name="assets/a b.pdf", description=None, content="AP+A", encoding="base64"
            )
        )
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_skill_package_service] = lambda: package
    app.dependency_overrides[deps.get_skill_service] = lambda: skills
    app.dependency_overrides[deps.get_skill_version_service] = lambda: versions
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, package, skills, versions, ctx
    finally:
        app.dependency_overrides.clear()


async def test_preview_then_apply_preserves_relative_binary_payload(package_client) -> None:
    client, service, _, _, ctx = package_client
    files = [("files", ("folder/SKILL.md", b"body")), ("files", ("folder/assets/a.pdf", b"\0\xff"))]
    response = await client.post(
        "/api/v1/skills/import/preview", data={"format": "directory"}, files=files
    )
    assert response.status_code == 200
    assert response.json()["execution"] == "none"
    service.preview.assert_awaited_once_with(
        ctx, [("folder/SKILL.md", b"body"), ("folder/assets/a.pdf", b"\0\xff")], archive=False
    )
    response = await client.post(
        "/api/v1/skills/import", data={"format": "directory", "fingerprint": "a" * 64}, files=files
    )
    assert response.status_code == 201
    service.apply.assert_awaited_once_with(
        ctx,
        [("folder/SKILL.md", b"body"), ("folder/assets/a.pdf", b"\0\xff")],
        archive=False,
        expected_fingerprint="a" * 64,
    )


async def test_format_and_fingerprint_are_required_not_inferred(package_client) -> None:
    client, service, *_ = package_client
    response = await client.post(
        "/api/v1/skills/import",
        data={"format": "zip", "fingerprint": "bad"},
        files={"files": ("skill.zip", b"zip")},
    )
    assert response.status_code == 422
    service.apply.assert_not_awaited()
    service.preview.side_effect = BadRequestError(message="Unsafe package")
    response = await client.post(
        "/api/v1/skills/import/preview",
        data={"format": "zip"},
        files={"files": ("skill.zip", b"zip")},
    )
    assert response.status_code == 400


async def test_downloads_authorized_live_and_immutable_bytes(package_client) -> None:
    client, _, skills, versions, ctx = package_client
    response = await client.get(f"/api/v1/skills/{SKILL}/resources/{RESOURCE}/download")
    assert response.status_code == 200
    assert response.content == b"\0\xff\x80"
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''a%20b.pdf"
    skills.get_resource.assert_awaited_once_with(ctx, SKILL, RESOURCE)
    response = await client.get(
        f"/api/v1/skills/{SKILL}/versions/{VERSION}/download/assets/a%20b.pdf"
    )
    assert response.content == b"\0\xff\x80"
    versions.read_resource.assert_awaited_once_with(ctx, SKILL, VERSION, "assets/a b.pdf")
    versions.read_resource.side_effect = NotFoundError(message="Skill not found")
    assert (
        await client.get(f"/api/v1/skills/{SKILL}/versions/{VERSION}/download/assets/a.pdf")
    ).status_code == 404


async def test_multipart_file_count_matches_the_package_contract(package_client) -> None:
    from app.core.skill_files import MAX_SKILL_PACKAGE_FILES

    client, service, *_ = package_client
    files = [
        ("files", (f"references/{index}.txt", b"x")) for index in range(MAX_SKILL_PACKAGE_FILES)
    ]
    response = await client.post(
        "/api/v1/skills/import/preview", data={"format": "directory"}, files=files
    )
    assert response.status_code == 200
    assert len(service.preview.await_args.args[1]) == MAX_SKILL_PACKAGE_FILES
    service.preview.reset_mock()
    response = await client.post(
        "/api/v1/skills/import/preview",
        data={"format": "directory"},
        files=[*files, ("files", ("extra.txt", b"x"))],
    )
    assert response.status_code == 400
    service.preview.assert_not_awaited()


async def test_bounded_upload_reads_refuse_excess_bytes_and_multiple_archives(
    package_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes.v1 import skills

    client, service, *_ = package_client
    monkeypatch.setattr(skills, "MAX_SKILL_FILE_BYTES", 2)
    response = await client.post(
        "/api/v1/skills/import/preview",
        data={"format": "directory"},
        files={"files": ("SKILL.md", b"over")},
    )
    assert response.status_code == 400
    service.preview.assert_not_awaited()
    response = await client.post(
        "/api/v1/skills/import/preview",
        data={"format": "zip"},
        files=[("files", ("a.zip", b"a")), ("files", ("b.zip", b"b"))],
    )
    assert response.status_code == 400
    service.preview.assert_not_awaited()
