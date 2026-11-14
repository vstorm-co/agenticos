"""Static previews reuse immutable versions and retain access decisions at the service."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import (
    AuthorizationError,
    ConfigurationError,
    ExternalServiceError,
    NotFoundError,
)
from app.services import artifact_thumbnails as thumbnails
from app.services.artifact import ArtifactService
from app.services.artifact_render import Rendered, RenderRequest

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def clear_images():
    thumbnails._IMAGES.clear()
    yield
    thumbnails._IMAGES.clear()


def request() -> RenderRequest:
    return RenderRequest(document=b"<p>Report</p>", nonce="test", bindings={})


async def test_static_preview_reuses_the_same_version_and_renders_a_new_one():
    version = uuid4()
    with patch.object(
        thumbnails.artifact_render, "render", AsyncMock(return_value=Rendered(image=b"jpeg"))
    ) as render:
        first = await thumbnails.render_thumbnail(version, request())
        repeated = await thumbnails.render_thumbnail(version, request())
        new = await thumbnails.render_thumbnail(uuid4(), request())
    assert first.state == repeated.state == new.state == "ready"
    assert first.image == "data:image/jpeg;base64," + base64.b64encode(b"jpeg").decode()
    assert render.await_count == 2


async def test_preview_cache_expires_and_respects_entry_and_byte_bounds(monkeypatch):
    monkeypatch.setattr(thumbnails, "_MAX_BYTES", 5)
    monkeypatch.setattr(thumbnails, "_MAX_ENTRIES", 2)
    clock = [0.0]
    monkeypatch.setattr(thumbnails, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    ids = [uuid4() for _ in range(4)]
    with patch.object(
        thumbnails.artifact_render, "render", AsyncMock(return_value=Rendered(image=b"12"))
    ):
        for version in ids[:3]:
            await thumbnails.render_thumbnail(version, request())
        assert list(thumbnails._IMAGES) == ids[1:3]
        clock[0] = thumbnails._TTL_SECONDS
        await thumbnails.render_thumbnail(ids[3], request())
        assert list(thumbnails._IMAGES) == ids[3:]


async def test_an_oversized_image_is_served_but_not_retained(monkeypatch):
    monkeypatch.setattr(thumbnails, "_MAX_BYTES", 2)
    with patch.object(
        thumbnails.artifact_render, "render", AsyncMock(return_value=Rendered(image=b"large"))
    ):
        result = await thumbnails.render_thumbnail(uuid4(), request())
    assert result.state == "ready"
    assert not thumbnails._IMAGES


@pytest.mark.parametrize(
    "error",
    [ConfigurationError(message="not configured"), ExternalServiceError(message="unavailable")],
)
async def test_renderer_absence_and_failure_are_explicit_without_an_executable_fallback(error):
    with patch.object(thumbnails.artifact_render, "render", AsyncMock(side_effect=error)):
        result = await thumbnails.render_thumbnail(uuid4(), request())
    assert result.state == "unavailable" and result.image is None
    assert not thumbnails._IMAGES


async def test_a_timed_out_render_is_not_saved_as_a_thumbnail():
    with patch.object(
        thumbnails.artifact_render, "render", AsyncMock(return_value=Rendered(timed_out=True))
    ):
        result = await thumbnails.render_thumbnail(uuid4(), request())
    assert result.state == "unavailable"
    assert not thumbnails._IMAGES


async def test_pdf_requests_cannot_enter_the_shared_thumbnail_cache():
    with pytest.raises(ValueError, match="no live data"):
        await thumbnails.render_thumbnail(
            uuid4(), RenderRequest(document=b"", nonce="n", bindings={}, output="pdf")
        )


@pytest.mark.security
async def test_service_checks_access_before_using_any_cached_image():
    service = ArtifactService(MagicMock())
    service.view = AsyncMock(side_effect=AuthorizationError(message="No access"))
    with (
        patch.object(thumbnails, "render_thumbnail", AsyncMock()) as render,
        pytest.raises(AuthorizationError),
    ):
        await service.thumbnail(MagicMock(), uuid4(), version_id=uuid4())
    render.assert_not_awaited()


async def test_service_only_renders_the_authorized_version_without_live_data():
    version_id, artifact_id = uuid4(), uuid4()
    service = ArtifactService(MagicMock())
    service.view = AsyncMock(
        return_value=SimpleNamespace(version=SimpleNamespace(id=version_id), nonce="n")
    )
    version = MagicMock(id=version_id, bindings=[{"name": "private_records"}])
    actor = MagicMock()
    with (
        patch("app.services.artifact.artifact_repo.get_version", AsyncMock(return_value=version)),
        patch("app.services.artifact._load_version", AsyncMock(return_value=b"source")),
        patch("app.services.artifact.render", return_value=b"page") as document,
        patch.object(thumbnails, "render_thumbnail", AsyncMock()) as render,
    ):
        await service.thumbnail(actor, artifact_id, version_id=version_id)
    service.view.assert_awaited_once_with(actor, artifact_id, version_id=version_id)
    document.assert_called_once_with(version, b"source", title="", nonce="n", live=True)
    assert render.call_args.args[1].bindings == {}


async def test_version_deleted_between_authorization_and_read_is_reported_missing():
    service = ArtifactService(MagicMock())
    service.view = AsyncMock(return_value=SimpleNamespace(version=SimpleNamespace(id=uuid4())))
    with (
        patch("app.services.artifact.artifact_repo.get_version", AsyncMock(return_value=None)),
        pytest.raises(NotFoundError),
    ):
        await service.thumbnail(MagicMock(), uuid4())
