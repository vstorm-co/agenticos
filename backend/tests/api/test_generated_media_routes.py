"""Serving generated media: the caller's own organization, and nobody else's."""

import uuid
from collections.abc import AsyncIterator
from io import BytesIO

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.file_storage import LocalFileStorage, S3FileStorage
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


class _ObjectStore:
    """Enough of a boto3 S3 client to serve objects and record the ranges asked for."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.ranges: list[str] = []

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, int]:
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, *, Bucket: str, Key: str, Range: str) -> dict[str, BytesIO]:
        self.ranges.append(Range)
        first, last = Range.removeprefix("bytes=").split("-")
        return {"Body": BytesIO(self.objects[Key][int(first) : int(last) + 1])}


class TestStreamingRatherThanLoading:
    """A clip can be hundreds of megabytes and this route has no rate limit (#2310).

    Loading the whole file to slice a range out of it held the whole clip once per
    concurrent request; these assert the bytes are read a span at a time.
    """

    async def test_a_range_is_read_alone_and_its_length_is_stated(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        organization_id = uuid.uuid4()
        filename = await save_generated_media(organization_id, b"0123456789", filename="video.mp4")
        _as_org(organization_id)
        asked: list[tuple[int, int]] = []
        real_open_range = LocalFileStorage.open_range

        async def open_range(
            self: LocalFileStorage, path: str, start: int, end: int
        ) -> AsyncIterator[bytes]:
            asked.append((start, end))
            return await real_open_range(self, path, start, end)

        async def load(self: LocalFileStorage, path: str) -> bytes:
            raise AssertionError("the whole file must not be loaded")

        monkeypatch.setattr(LocalFileStorage, "open_range", open_range)
        monkeypatch.setattr(LocalFileStorage, "load", load)

        response = await client.get(f"/api/v1/generated/{filename}", headers={"Range": "bytes=2-5"})

        assert response.status_code == 206
        assert response.content == b"2345"
        assert response.headers["content-length"] == "4"
        assert response.headers["content-range"] == "bytes 2-5/10"
        assert asked == [(2, 5)]

    async def test_a_whole_file_states_its_length_and_keeps_its_headers(self, client: AsyncClient):
        organization_id = uuid.uuid4()
        filename = await save_generated_media(organization_id, b"0123456789", filename="video.mp4")
        _as_org(organization_id)

        response = await client.get(f"/api/v1/generated/{filename}?download=true")

        assert response.status_code == 200
        assert response.content == b"0123456789"
        assert response.headers["content-length"] == "10"
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith("attachment")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == "sandbox"

    async def test_an_empty_file_is_an_empty_answer(self, client: AsyncClient):
        organization_id = uuid.uuid4()
        filename = await save_generated_media(organization_id, b"", filename="speech.mp3")
        _as_org(organization_id)

        response = await client.get(f"/api/v1/generated/{filename}")

        assert response.status_code == 200
        assert response.content == b""
        assert response.headers["content-type"] == "audio/mpeg"

    async def test_a_file_gone_between_measuring_and_reading_is_a_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        """A retention sweep or a deleted conversation can take it in between;
        nothing has gone out yet, so the answer is still a 404, not a dead body."""
        organization_id = uuid.uuid4()
        filename = await save_generated_media(organization_id, b"0123", filename="video.mp4")
        _as_org(organization_id)

        async def open_range(
            self: LocalFileStorage, path: str, start: int, end: int
        ) -> AsyncIterator[bytes]:
            raise FileNotFoundError(path)

        monkeypatch.setattr(LocalFileStorage, "open_range", open_range)

        response = await client.get(f"/api/v1/generated/{filename}")

        assert response.status_code == 404

    async def test_an_object_store_is_asked_for_the_range_alone(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        organization_id = uuid.uuid4()
        filename = "abc123_video.mp4"
        store = _ObjectStore({f"generated_{organization_id}/{filename}": b"0123456789"})
        storage = S3FileStorage(store, "files")
        monkeypatch.setattr("app.services.generated_media.get_file_storage", lambda: storage)
        monkeypatch.setattr("app.api.routes.v1._workspace_bytes.get_file_storage", lambda: storage)
        _as_org(organization_id)

        response = await client.get(f"/api/v1/generated/{filename}", headers={"Range": "bytes=-3"})

        assert response.status_code == 206
        assert response.content == b"789"
        assert response.headers["content-range"] == "bytes 7-9/10"
        assert store.ranges == ["bytes=7-9"]

    @pytest.mark.security
    async def test_an_object_store_answers_another_tenant_with_a_not_found(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        owner = uuid.uuid4()
        store = _ObjectStore({f"generated_{owner}/abc123_video.mp4": b"private"})
        storage = S3FileStorage(store, "files")
        monkeypatch.setattr("app.services.generated_media.get_file_storage", lambda: storage)
        _as_org(uuid.uuid4())

        response = await client.get("/api/v1/generated/abc123_video.mp4")

        assert response.status_code == 404
        assert store.ranges == []
