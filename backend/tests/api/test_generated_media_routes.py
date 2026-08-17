"""Serving generated images: the caller's own organization, and nobody else's."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.generated_media import save_generated_image

pytestmark = pytest.mark.anyio


def _as_org(organization_id: uuid.UUID) -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=organization_id, role=OrgRoleName.MEMBER
    )


@pytest.fixture(autouse=True)
def _media_dir(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)


async def test_a_generated_image_is_served_inline_to_its_own_organization(client: AsyncClient):
    organization_id = uuid.uuid4()
    filename = await save_generated_image(organization_id, b"\x89PNG-body", image_format="png")
    _as_org(organization_id)

    response = await client.get(f"/api/v1/generated/{filename}")

    assert response.status_code == 200
    assert response.content == b"\x89PNG-body"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].startswith("inline")


async def test_another_organization_gets_a_not_found(client: AsyncClient):
    filename = await save_generated_image(uuid.uuid4(), b"private", image_format="png")
    _as_org(uuid.uuid4())

    response = await client.get(f"/api/v1/generated/{filename}")

    assert response.status_code == 404


async def test_a_missing_image_is_a_not_found(client: AsyncClient):
    _as_org(uuid.uuid4())

    response = await client.get("/api/v1/generated/deadbeef1234_image.png")

    assert response.status_code == 404


async def test_download_forces_an_attachment(client: AsyncClient):
    organization_id = uuid.uuid4()
    filename = await save_generated_image(organization_id, b"\x89PNG-body", image_format="png")
    _as_org(organization_id)

    response = await client.get(f"/api/v1/generated/{filename}?download=true")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment")
