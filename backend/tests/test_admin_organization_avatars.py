"""Organization identity is visible in the deployment admin directory."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.api.routes.v1.admin_stats import get_admin_organization_avatar
from app.core.exceptions import NotFoundError
from app.db.models.organization import Organization
from app.services.admin import AdminService

pytestmark = pytest.mark.anyio


async def test_directory_preserves_avatar_presence_and_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = Organization(
        id=uuid4(),
        name="Northwind",
        slug="nw",
        is_personal=False,
        avatar_url="avatars/orgs/nw.png",
        avatar_color=4,
    )
    monkeypatch.setattr(
        "app.services.admin.organization_repo.admin_list_with_counts",
        AsyncMock(return_value=([(org, 8, 14, None, None, None)], 1)),
    )
    result = await AdminService(AsyncMock()).list_organizations()
    assert result["items"][0]["has_avatar"] is True
    assert result["items"][0]["avatar_color"] == 4
    assert "avatar_url" not in result["items"][0]


@pytest.mark.parametrize("present", [True, False])
async def test_avatar_path_requires_an_existing_uploaded_avatar(
    monkeypatch: pytest.MonkeyPatch, present: bool
) -> None:
    org = Organization(
        id=uuid4(), name="Northwind", slug="nw", avatar_url="avatars/nw.png" if present else None
    )
    monkeypatch.setattr(
        "app.services.admin.organization_repo.get_by_id", AsyncMock(return_value=org)
    )
    if present:
        assert await AdminService(AsyncMock()).organization_avatar_path(org.id) == "avatars/nw.png"
    else:
        with pytest.raises(NotFoundError):
            await AdminService(AsyncMock()).organization_avatar_path(org.id)


async def test_missing_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.admin.organization_repo.get_by_id", AsyncMock(return_value=None)
    )
    with pytest.raises(NotFoundError):
        await AdminService(AsyncMock()).organization_avatar_path(uuid4())


async def test_admin_avatar_serves_only_sniffed_image_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    path = tmp_path / "logo.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    service = MagicMock(organization_avatar_path=AsyncMock(return_value="logo.png"))
    response = await get_admin_organization_avatar(uuid4(), service, MagicMock())
    assert response.media_type == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"].startswith("private")
    path.write_bytes(b"<script>bad()</script>")
    with pytest.raises(NotFoundError):
        await get_admin_organization_avatar(uuid4(), service, MagicMock())
