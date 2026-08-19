"""The branding endpoints, through the app.

Three questions a service-level test cannot answer, and each of them is the reason
one of these routes is shaped the way it is:

**Who may read what.** `GET /branding` is the one endpoint on this surface with no
session at all - the favicon is served above every tenant and the sign-in page
renders before a session exists - so a test that it stays reachable unauthenticated
is a test of the feature working. `/branding/notice` next to it must *not* be:
an announcement is an operator talking to the people using the deployment.

**Who may write.** Everything under `/admin/settings` is `CurrentAppAdmin`, and an
ordinary member reaching it is a 403 rather than a 200 with somebody else's
identity in it.

**What a stored file is served as.** The image routes decide the media type here
rather than letting Starlette guess it from a suffix on disk: this is served from
the origin the app's own pages run on, and a file that is not a picture must not go
out as whatever it looks like.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.deps import get_current_user, get_db_session
from app.api.routes.v1 import _branding_bytes
from app.core.config import settings
from app.main import app
from app.schemas.deployment_settings import (
    BrandingRead,
    DeploymentSettingsRead,
    NoticeRead,
)

pytestmark = pytest.mark.anyio


class _User:
    def __init__(self, *, admin: bool) -> None:
        self.id = uuid4()
        self.email = "ops@example.com" if admin else "member@example.com"
        self.is_app_admin = admin
        self.is_active = True
        self.created_at = datetime.now(UTC)


class _Service:
    """The settings service, recording what the routes asked it for."""

    def __init__(self) -> None:
        self.read_value = DeploymentSettingsRead(app_name="Acme AI", announcement="Window at 22:00")
        self.branding_value = BrandingRead(app_name="Acme AI")
        self.notice_value = NoticeRead(message="Window at 22:00", level="warning")
        self.stored: str | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def branding(self) -> BrandingRead:
        return self.branding_value

    async def notice(self) -> NoticeRead:
        return self.notice_value

    async def read(self) -> DeploymentSettingsRead:
        return self.read_value

    async def update(self, **kwargs: Any) -> DeploymentSettingsRead:
        self.calls.append(("update", kwargs))
        return self.read_value

    async def set_image(self, **kwargs: Any) -> DeploymentSettingsRead:
        self.calls.append(("set_image", kwargs))
        return self.read_value

    async def clear_image(self, **kwargs: Any) -> DeploymentSettingsRead:
        self.calls.append(("clear_image", kwargs))
        return self.read_value

    async def image_path(self, _kind: str) -> str | None:
        return self.stored


@pytest.fixture
def service() -> _Service:
    return _Service()


def _wire(service: _Service, user: _User | None) -> None:
    app.dependency_overrides[deps.get_deployment_settings_service] = lambda: service
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user


@pytest.fixture
async def anyone(service: _Service) -> AsyncGenerator[AsyncClient, None]:
    """No session at all - the state the sign-in page and the favicon fetch are in."""
    _wire(service, None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def admin(service: _Service) -> AsyncGenerator[AsyncClient, None]:
    _wire(service, _User(admin=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def member(service: _Service) -> AsyncGenerator[AsyncClient, None]:
    _wire(service, _User(admin=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


class TestReadingTheIdentity:
    async def test_a_caller_with_no_session_can_read_it(self, anyone: AsyncClient):
        """Structural rather than a convenience: a surface that could not read this
        could not draw its own name."""
        response = await anyone.get(f"{settings.API_V1_STR}/branding")

        assert response.status_code == 200
        assert response.json()["app_name"] == "Acme AI"

    async def test_the_announcement_needs_a_session(self, anyone: AsyncClient):
        response = await anyone.get(f"{settings.API_V1_STR}/branding/notice")

        assert response.status_code == 401

    async def test_a_signed_in_member_reads_the_announcement(self, member: AsyncClient):
        """Any signed-in user, not only an administrator: the banner is for everybody
        using the deployment."""
        response = await member.get(f"{settings.API_V1_STR}/branding/notice")

        assert response.status_code == 200
        assert response.json() == {"message": "Window at 22:00", "level": "warning"}


class TestTheAdminSurface:
    async def test_an_administrator_reads_the_whole_form(self, admin: AsyncClient):
        response = await admin.get(f"{settings.API_V1_STR}/admin/settings")

        assert response.status_code == 200
        assert response.json()["announcement"] == "Window at 22:00"

    async def test_a_member_is_refused(self, member: AsyncClient):
        response = await member.get(f"{settings.API_V1_STR}/admin/settings")

        assert response.status_code == 403

    async def test_a_caller_with_no_session_is_refused(self, anyone: AsyncClient):
        response = await anyone.get(f"{settings.API_V1_STR}/admin/settings")

        assert response.status_code == 401

    async def test_a_patch_carries_the_actor_and_the_data(
        self, admin: AsyncClient, service: _Service
    ):
        response = await admin.patch(
            f"{settings.API_V1_STR}/admin/settings", json={"app_name": "Acme AI"}
        )

        assert response.status_code == 200
        name, kwargs = service.calls[0]
        assert name == "update"
        assert kwargs["data"].app_name == "Acme AI"
        assert kwargs["actor_user_id"] is not None

    async def test_a_member_cannot_patch(self, member: AsyncClient, service: _Service):
        response = await member.patch(
            f"{settings.API_V1_STR}/admin/settings", json={"app_name": "Not Yours"}
        )

        assert response.status_code == 403
        assert service.calls == []

    async def test_an_image_path_is_not_something_a_caller_may_name(
        self, admin: AsyncClient, service: _Service
    ):
        """The upload writes the storage key itself. A caller who could choose it could
        point this deployment's public logo at whatever the storage backend holds, so
        the field is not in the update schema at all - and a request naming it reaches
        the service with nothing in it."""
        response = await admin.patch(
            f"{settings.API_V1_STR}/admin/settings",
            json={"logo_path": "../../etc/passwd", "favicon_path": "x"},
        )

        assert response.status_code == 200
        _name, kwargs = service.calls[0]
        assert kwargs["data"].model_fields_set == set()

    @pytest.mark.parametrize("kind", ["logo", "favicon"])
    async def test_uploading_hands_the_bytes_and_the_declared_type_to_the_service(
        self, admin: AsyncClient, service: _Service, kind: str
    ):
        response = await admin.post(
            f"{settings.API_V1_STR}/admin/settings/{kind}",
            files={"file": ("mark.png", b"pngbytes", "image/png")},
        )

        assert response.status_code == 200
        name, kwargs = service.calls[0]
        assert name == "set_image"
        assert kwargs["kind"] == kind
        assert kwargs["file_data"] == b"pngbytes"
        assert kwargs["content_type"] == "image/png"

    @pytest.mark.parametrize("kind", ["logo", "favicon"])
    async def test_clearing_answers_the_settings_rather_than_no_content(
        self, admin: AsyncClient, service: _Service, kind: str
    ):
        """The form re-renders from this response, and a 204 would leave it guessing."""
        response = await admin.delete(f"{settings.API_V1_STR}/admin/settings/{kind}")

        assert response.status_code == 200
        assert response.json()["app_name"] == "Acme AI"
        assert service.calls[0][1]["kind"] == kind

    @pytest.mark.parametrize("kind", ["logo", "favicon"])
    async def test_a_member_cannot_upload_or_clear(
        self, member: AsyncClient, service: _Service, kind: str
    ):
        upload = await member.post(
            f"{settings.API_V1_STR}/admin/settings/{kind}",
            files={"file": ("mark.png", b"x", "image/png")},
        )
        clear = await member.delete(f"{settings.API_V1_STR}/admin/settings/{kind}")

        assert upload.status_code == 403
        assert clear.status_code == 403
        assert service.calls == []


class TestServingTheBytes:
    @pytest.mark.parametrize("kind", ["logo", "favicon"])
    async def test_no_upload_is_a_404(self, anyone: AsyncClient, service: _Service, kind: str):
        """The ordinary state of a deployment using the built-in mark, and what the
        frontend reads as "draw your own"."""
        service.stored = None

        response = await anyone.get(f"{settings.API_V1_STR}/branding/{kind}")

        assert response.status_code == 404

    async def test_a_row_pointing_at_a_file_that_is_gone_is_a_404(
        self, anyone: AsyncClient, service: _Service, monkeypatch
    ):
        service.stored = "deployment/vanished.png"
        monkeypatch.setattr(_branding_bytes, "get_file_storage", lambda: _Storage(full_path=None))

        response = await anyone.get(f"{settings.API_V1_STR}/branding/logo")

        assert response.status_code == 404

    async def test_the_stored_bytes_are_served_with_the_type_decided_here(
        self, anyone: AsyncClient, service: _Service, monkeypatch, tmp_path: Path
    ):
        mark = tmp_path / "logo.png"
        mark.write_bytes(b"\x89PNG\r\n")
        service.stored = "deployment/logo.png"
        monkeypatch.setattr(_branding_bytes, "get_file_storage", lambda: _Storage(full_path=mark))

        response = await anyone.get(f"{settings.API_V1_STR}/branding/logo")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == b"\x89PNG\r\n"

    async def test_it_is_served_without_a_session(
        self, anyone: AsyncClient, service: _Service, monkeypatch, tmp_path: Path
    ):
        """A browser fetching a favicon carries no cookie this API would read."""
        mark = tmp_path / "favicon.gif"
        mark.write_bytes(b"GIF89a")
        service.stored = "deployment/favicon.gif"
        monkeypatch.setattr(_branding_bytes, "get_file_storage", lambda: _Storage(full_path=mark))

        response = await anyone.get(f"{settings.API_V1_STR}/branding/favicon")

        assert response.status_code == 200

    async def test_a_stored_file_that_is_not_a_picture_is_refused(
        self, anyone: AsyncClient, service: _Service, monkeypatch, tmp_path: Path
    ):
        """A stored file keeps whatever extension the upload minted, and this is
        served from the origin the app's own pages run on - so a bare `FileResponse`
        would let Starlette guess `text/html` and serve a script. Refused rather than
        corrected: this route hands out one image."""
        script = tmp_path / "logo.html"
        script.write_text("<script>alert(1)</script>")
        service.stored = "deployment/logo.html"
        monkeypatch.setattr(_branding_bytes, "get_file_storage", lambda: _Storage(full_path=script))

        response = await anyone.get(f"{settings.API_V1_STR}/branding/logo")

        assert response.status_code == 404

    async def test_it_forbids_content_type_sniffing(
        self, anyone: AsyncClient, service: _Service, monkeypatch, tmp_path: Path
    ):
        mark = tmp_path / "logo.webp"
        mark.write_bytes(b"RIFF")
        service.stored = "deployment/logo.webp"
        monkeypatch.setattr(_branding_bytes, "get_file_storage", lambda: _Storage(full_path=mark))

        response = await anyone.get(f"{settings.API_V1_STR}/branding/logo")

        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_it_may_be_cached_for_a_long_time(
        self, anyone: AsyncClient, service: _Service, monkeypatch, tmp_path: Path
    ):
        """Safe because the address carries the row's write time: replacing the image
        changes the `?v=` the branding response hands out, so a long-lived copy is
        only ever reused for bytes that have not changed."""
        mark = tmp_path / "logo.jpg"
        mark.write_bytes(b"\xff\xd8\xff")
        service.stored = "deployment/logo.jpg"
        monkeypatch.setattr(_branding_bytes, "get_file_storage", lambda: _Storage(full_path=mark))

        response = await anyone.get(f"{settings.API_V1_STR}/branding/logo")

        assert "immutable" in response.headers["cache-control"]


class _Storage:
    def __init__(self, *, full_path: Path | None) -> None:
        self._full_path = full_path

    def get_full_path(self, _stored: str) -> Path | None:
        return self._full_path
