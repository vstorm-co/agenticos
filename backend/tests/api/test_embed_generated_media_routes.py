"""A visitor's generated file: opened by the link their socket minted, and by nothing else.

The hosted page has no session, so the console's `/generated/{filename}` answered
its cards with a 401 (#2309). This route answers to a link instead, and every
refusal is the same 404 a missing file gets - a guessed address must not be a way
to learn what exists.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.logging import PiiRedactionFilter
from app.services.embed_generated_media import media_path, media_token
from app.services.generated_media import save_generated_media

pytestmark = pytest.mark.anyio

KEY = "pk_hosted-page-key"
OTHER_KEY = "pk_another-page-key"


@pytest.fixture(autouse=True)
def _media_dir(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)


def _embeds(**by_key: MagicMock):
    """Answer the unscoped key lookup the route makes, from this table."""

    async def lookup(_db: object, public_key: str) -> MagicMock | None:
        return by_key.get(public_key)

    return patch(
        "app.services.embed_generated_media.agent_embed_repo.get_by_key",
        AsyncMock(side_effect=lookup),
    )


def _embed(organization_id: uuid.UUID, *, active: bool = True) -> MagicMock:
    return MagicMock(organization_id=organization_id, is_active=active)


def _link(filename: str, *, key: str = KEY, token: str | None = None) -> str:
    token = token or media_token(key, filename, now=datetime.now(UTC))
    return f"/api/v1/embed/{key}/generated/{filename}?token={token}"


async def test_a_visitor_opens_the_image_their_conversation_made(client: AsyncClient):
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"\x89PNG-body", filename="image.png")

    with _embeds(**{KEY: _embed(organization_id)}):
        response = await client.get(_link(filename))

    assert response.status_code == 200
    assert response.content == b"\x89PNG-body"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"


@pytest.mark.parametrize(
    ("name", "media_type"), [("speech.mp3", "audio/mpeg"), ("video.mp4", "video/mp4")]
)
async def test_a_clip_plays_in_ranges(client: AsyncClient, name: str, media_type: str):
    """Safari plays an MP4 only from ranged answers, so the range is honoured here too."""
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"0123456789", filename=name)

    with _embeds(**{KEY: _embed(organization_id)}):
        response = await client.get(_link(filename), headers={"Range": "bytes=2-5"})

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == media_type


async def test_a_range_past_the_end_is_not_satisfiable(client: AsyncClient):
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"0123", filename="video.mp4")

    with _embeds(**{KEY: _embed(organization_id)}):
        response = await client.get(_link(filename), headers={"Range": "bytes=9-"})

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */4"


async def test_a_link_for_one_file_does_not_open_another_conversations(client: AsyncClient):
    """Same organization, same embed: the other file was never signed for this visitor."""
    organization_id = uuid.uuid4()
    mine = await save_generated_media(organization_id, b"mine", filename="image.png")
    theirs = await save_generated_media(organization_id, b"theirs", filename="image.png")
    my_token = media_token(KEY, mine, now=datetime.now(UTC))

    with _embeds(**{KEY: _embed(organization_id)}):
        response = await client.get(_link(theirs, token=my_token))

    assert response.status_code == 404
    assert b"theirs" not in response.content


async def test_another_organizations_file_is_out_of_reach(client: AsyncClient):
    """Signed on this embed, the bytes are read from *its* organization's directory."""
    filename = await save_generated_media(uuid.uuid4(), b"private", filename="image.png")

    with _embeds(**{KEY: _embed(uuid.uuid4())}):
        response = await client.get(_link(filename))

    assert response.status_code == 404


async def test_a_link_minted_on_another_embed_opens_nothing_here(client: AsyncClient):
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"body", filename="image.png")
    elsewhere = media_token(OTHER_KEY, filename, now=datetime.now(UTC))

    with _embeds(**{KEY: _embed(organization_id), OTHER_KEY: _embed(organization_id)}):
        response = await client.get(_link(filename, token=elsewhere))

    assert response.status_code == 404


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "not-a-token",
        f"{int(datetime.now(UTC).timestamp()) + 3600}.{'0' * 64}",
        "1.",
    ],
    ids=["absent", "empty", "malformed", "forged", "truncated"],
)
async def test_a_bad_token_is_a_not_found(client: AsyncClient, token: str | None):
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"body", filename="image.png")
    lookup = AsyncMock(return_value=_embed(organization_id))
    url = f"/api/v1/embed/{KEY}/generated/{filename}"

    with patch("app.services.embed_generated_media.agent_embed_repo.get_by_key", lookup):
        response = await client.get(url if token is None else f"{url}?token={token}")

    assert response.status_code == 404
    # Refused on the signature, before any query.
    lookup.assert_not_awaited()


async def test_an_expired_link_is_a_not_found(client: AsyncClient):
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"body", filename="image.png")
    stale = media_token(KEY, filename, now=datetime.now(UTC) - timedelta(days=1))

    with _embeds(**{KEY: _embed(organization_id)}):
        response = await client.get(_link(filename, token=stale))

    assert response.status_code == 404


@pytest.mark.parametrize("embed", [None, "paused"], ids=["deleted", "paused"])
async def test_a_page_that_is_gone_or_paused_opens_nothing(client: AsyncClient, embed: str | None):
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"body", filename="image.png")
    table = {} if embed is None else {KEY: _embed(organization_id, active=False)}

    with _embeds(**table):
        response = await client.get(_link(filename))

    assert response.status_code == 404


async def test_a_missing_file_gets_the_same_answer_as_a_refusal(client: AsyncClient):
    """No existence oracle: a valid link to nothing and a forged one read the same."""
    organization_id = uuid.uuid4()

    with _embeds(**{KEY: _embed(organization_id)}):
        missing = await client.get(_link("deadbeef_image.png"))
        forged = await client.get(_link("deadbeef_image.png", token=f"9999999999.{'a' * 64}"))

    assert missing.status_code == forged.status_code == 404
    assert missing.json()["error"]["code"] == forged.json()["error"]["code"]


async def test_the_token_is_never_echoed_or_logged(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
):
    organization_id = uuid.uuid4()
    theirs = await save_generated_media(organization_id, b"theirs", filename="image.png")
    token = media_token(KEY, "some-other-file.png", now=datetime.now(UTC))
    signature = token.split(".")[1]

    with caplog.at_level(logging.DEBUG), _embeds(**{KEY: _embed(organization_id)}):
        response = await client.get(_link(theirs, token=token))

    assert response.status_code == 404
    assert signature not in response.text
    # The server's own lines - the test client logs the URL it was asked for, which
    # is this test's request rather than anything the API wrote.
    server = [record.getMessage() for record in caplog.records if record.name.startswith("app")]
    assert server, "the refusal is logged"
    assert not any(signature in line for line in server)


def test_a_link_that_reaches_a_log_line_is_redacted():
    """An access log writes the query string, so the link's token must not survive it."""
    token = media_token(KEY, "abc_image.png", now=datetime.now(UTC))
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        "GET %s",
        (media_path(KEY, "abc_image.png", token),),
        None,
    )

    PiiRedactionFilter().filter(record)

    assert token.split(".")[1] not in record.getMessage()


async def test_a_range_is_read_without_the_whole_file(client: AsyncClient):
    """Streamed like the console's route (#2310): a link may be fetched 120 times a
    minute, and reading a long clip whole for each would hold it per request."""
    from app.services.file_storage import get_file_storage

    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"0123456789", filename="clip.mp4")
    storage = get_file_storage()

    with (
        _embeds(**{KEY: _embed(organization_id)}),
        patch.object(type(storage), "load", AsyncMock(side_effect=AssertionError("read whole"))),
    ):
        response = await client.get(_link(filename), headers={"Range": "bytes=2-5"})

    assert response.status_code == 206
    assert response.content == b"2345"


async def test_a_file_gone_after_it_was_measured_is_the_same_not_found(client: AsyncClient):
    organization_id = uuid.uuid4()
    filename = await save_generated_media(organization_id, b"\x89PNG-body", filename="image.png")

    with (
        _embeds(**{KEY: _embed(organization_id)}),
        patch(
            "app.api.routes.v1.embed_generated_media.streamed_file_response",
            AsyncMock(side_effect=FileNotFoundError),
        ),
    ):
        response = await client.get(_link(filename))

    assert response.status_code == 404
