"""Serving generated media: the caller's own organization, and nobody else's."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.generated_media import save_generated_media

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
    filename = await save_generated_media(organization_id, b"\x89PNG-body", filename="image.png")
    _as_org(organization_id)

    response = await client.get(f"/api/v1/generated/{filename}")

    assert response.status_code == 200
    assert response.content == b"\x89PNG-body"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].startswith("inline")


@pytest.mark.parametrize(
    ("name", "media_type"),
    [("speech.mp3", "audio/mpeg"), ("speech.wav", "audio/wav"), ("video.mp4", "video/mp4")],
)
async def test_generated_audio_and_video_play_inline(
    client: AsyncClient, name: str, media_type: str
):
    """Speech and video are typed for the player, not handed over as a download."""
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"media-body", filename=name)
    _as_org(organization_id)

    response = await client.get(f"/api/v1/generated/{filename}")

    assert response.status_code == 200
    assert response.headers["content-type"] == media_type
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_another_organization_gets_a_not_found(client: AsyncClient):
    filename = await save_generated_media(uuid.uuid4(), b"private", filename="image.png")
    _as_org(uuid.uuid4())

    response = await client.get(f"/api/v1/generated/{filename}")

    assert response.status_code == 404


async def test_a_missing_image_is_a_not_found(client: AsyncClient):
    _as_org(uuid.uuid4())

    response = await client.get("/api/v1/generated/deadbeef1234_image.png")

    assert response.status_code == 404


async def test_download_forces_an_attachment(client: AsyncClient):
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"\x89PNG-body", filename="image.png")
    _as_org(organization_id)

    response = await client.get(f"/api/v1/generated/{filename}?download=true")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize(
    ("asked", "body", "content_range"),
    [
        ("bytes=0-3", b"0123", "bytes 0-3/10"),
        ("bytes=6-", b"6789", "bytes 6-9/10"),
        ("bytes=-3", b"789", "bytes 7-9/10"),
        ("bytes=8-99", b"89", "bytes 8-9/10"),
    ],
    ids=["closed", "open", "suffix", "past the end"],
)
async def test_a_player_gets_the_byte_range_it_asks_for(
    client: AsyncClient, asked: str, body: bytes, content_range: str
):
    """WebKit plays an MP4 only from ranged responses - Safari, and the desktop app."""
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"0123456789", filename="video.mp4")
    _as_org(organization_id)

    response = await client.get(f"/api/v1/generated/{filename}", headers={"Range": asked})

    assert response.status_code == 206
    assert response.content == body
    assert response.headers["content-range"] == content_range
    assert response.headers["content-type"] == "video/mp4"


async def test_a_range_starting_past_the_end_is_not_satisfiable(client: AsyncClient):
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"0123", filename="video.mp4")
    _as_org(organization_id)

    response = await client.get(f"/api/v1/generated/{filename}", headers={"Range": "bytes=4-"})

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */4"


@pytest.mark.parametrize("asked", ["bytes=0-1,4-5", "items=0-1", "bytes=-", "bytes=3-1"])
async def test_a_range_it_does_not_serve_gets_the_whole_file_or_a_refusal(
    client: AsyncClient, asked: str
):
    """A multi-range or another unit is answered whole, which RFC 9110 allows; a
    reversed range cannot be satisfied."""
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"0123", filename="video.mp4")
    _as_org(organization_id)

    response = await client.get(f"/api/v1/generated/{filename}", headers={"Range": asked})

    if asked == "bytes=3-1":
        assert response.status_code == 416
    else:
        assert response.status_code == 200
        assert response.content == b"0123"
        assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize(
    "asked", ["bytes=0-" + "9" * 5000, "bytes=" + "9" * 5000 + "-", "bytes=-" + "9" * 5000]
)
async def test_a_range_with_a_huge_number_gets_the_whole_file_rather_than_an_error(
    client: AsyncClient, asked: str
):
    """`int()` refuses a number past 4,300 digits; such a header is no range to honour."""
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"0123", filename="video.mp4")
    _as_org(organization_id)

    response = await client.get(f"/api/v1/generated/{filename}", headers={"Range": asked})

    assert response.status_code == 200
    assert response.content == b"0123"
