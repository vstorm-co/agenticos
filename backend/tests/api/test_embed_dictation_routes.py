"""`POST /embed/{public_key}/dictation`, over the wire (#1797).

What the route adds to `AgentEmbedService.admit_dictation` and `.dictate`: the
token as a form field rather than a header, the page's continuity key checked
for shape, a bounded read, and the CORS header a widget on somebody else's site
needs to read a refusal at all. The admission and gating rules themselves are in
`tests/test_agent_embed.py`.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.main import app
from app.services import transcription
from app.services.agent_embed import Admission, EmbedDenied
from app.services.rate_limit import Decision

pytestmark = pytest.mark.anyio

_URL = f"{settings.API_V1_STR}/embed/key-123/dictation"
_SITE = "https://shop.example"
_AUDIO = {"file": ("blob", b"audio", "audio/webm")}


async def _no_limit() -> None:
    return None


def _admitted(kind: str, visitor: str | None = None) -> Admission:
    embed = MagicMock()
    embed.kind = kind
    return Admission(embed=embed, visitor=visitor)


@pytest.fixture
def service() -> Iterator[MagicMock]:
    embeds = MagicMock()
    embeds.admit_dictation = AsyncMock(return_value=_admitted("widget"))
    embeds.dictate = AsyncMock(return_value="hello there")
    app.dependency_overrides[deps.get_agent_embed_service] = lambda: embeds
    app.dependency_overrides[deps.limit_embed_dictation] = _no_limit
    yield embeds
    app.dependency_overrides.clear()


async def test_a_widget_visitor_gets_the_text_and_their_site_may_read_it(
    client: AsyncClient, service: MagicMock
) -> None:
    response = await client.post(
        _URL, files=_AUDIO, data={"duration": "2.5"}, headers={"Origin": _SITE}
    )

    assert response.status_code == 200
    assert response.json() == {"text": "hello there"}
    assert response.headers["access-control-allow-origin"] == _SITE
    assert service.admit_dictation.await_args.kwargs["origin"] == _SITE
    sent = service.dictate.await_args.kwargs
    assert (sent["content"], sent["mime_type"], sent["reported_seconds"]) == (
        b"audio",
        "audio/webm",
        2.5,
    )


@pytest.mark.security
async def test_the_token_is_a_form_field_and_never_read_from_the_query(
    client: AsyncClient, service: MagicMock
) -> None:
    """A query string lands in access logs, and a header would need a preflight
    the global CORS policy refuses for somebody else's site."""
    await client.post(
        f"{_URL}?token=from-the-query",
        files=_AUDIO,
        data={"token": "signed"},
        headers={"Origin": _SITE},
    )

    assert service.admit_dictation.await_args.kwargs["token"] == "signed"


@pytest.mark.security
async def test_a_refused_admission_is_a_404_the_refused_site_cannot_read(
    client: AsyncClient, service: MagicMock
) -> None:
    service.admit_dictation.side_effect = EmbedDenied("origin not allowed")

    response = await client.post(_URL, files=_AUDIO, headers={"Origin": "https://evil.example"})

    assert response.status_code == 404
    assert "access-control-allow-origin" not in response.headers
    service.dictate.assert_not_awaited()


@pytest.mark.parametrize(
    ("raised", "status", "reason"),
    [
        (
            BadRequestError(message="Too long", details={"reason": "too_large"}),
            400,
            "too_large",
        ),
        (
            ExternalServiceError(message="Slow", details={"reason": "timeout"}),
            503,
            "timeout",
        ),
    ],
    ids=["too-large", "timeout"],
)
async def test_a_refusal_after_admission_reaches_the_widget_with_its_reason(
    client: AsyncClient,
    service: MagicMock,
    raised: Exception,
    status: int,
    reason: str,
) -> None:
    """Without the header the browser hides the response, `fetch` throws, and a
    recording that was too long reads to the visitor as being offline."""
    service.dictate.side_effect = raised

    response = await client.post(_URL, files=_AUDIO, headers={"Origin": _SITE})

    assert response.status_code == status
    assert response.json()["error"]["details"]["reason"] == reason
    assert response.headers["access-control-allow-origin"] == _SITE


async def test_an_embed_that_takes_no_recordings_is_a_readable_404(
    client: AsyncClient, service: MagicMock
) -> None:
    """Admitted, so the site may read it; refused, so it says nothing about why."""
    service.dictate.side_effect = EmbedDenied("not server")

    response = await client.post(_URL, files=_AUDIO, headers={"Origin": _SITE})

    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == _SITE


async def test_a_page_is_answered_without_echoing_an_origin(
    client: AsyncClient, service: MagicMock
) -> None:
    """A page is ours: its origin is in the global CORS list, and echoing any
    other would let a third-party site spend the page's transcription."""
    service.admit_dictation.return_value = _admitted("page")
    key = "a" * 32

    response = await client.post(
        _URL, files=_AUDIO, headers={"Origin": "https://evil.example", "X-Visitor-Key": key}
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") != "https://evil.example"
    assert service.admit_dictation.await_args.kwargs["visitor_key"] == key


async def test_a_visitor_key_of_the_wrong_shape_is_not_passed_on(
    client: AsyncClient, service: MagicMock
) -> None:
    await client.post(_URL, files=_AUDIO, headers={"X-Visitor-Key": "1"})

    assert service.admit_dictation.await_args.kwargs["visitor_key"] is None


async def test_the_upload_is_read_no_further_than_transcription_accepts(
    client: AsyncClient, service: MagicMock
) -> None:
    with patch.object(transcription, "MAX_BYTES", 4):
        await client.post(
            _URL, files={"file": ("blob", b"0123456789", "audio/webm")}, headers={"Origin": _SITE}
        )

    assert service.dictate.await_args.kwargs["content"] == b"01234"


async def test_a_rate_limited_caller_can_read_the_limit_from_any_site(
    client: AsyncClient, service: MagicMock
) -> None:
    """Counted before the key is read, and the same answer for every origin -
    so saying it to whoever asked tells them nothing about the embed."""
    app.dependency_overrides.pop(deps.limit_embed_dictation)
    with patch(
        "app.services.rate_limit.embed_dictation_allowed",
        new=AsyncMock(return_value=Decision(allowed=False, retry_after_seconds=60)),
    ):
        response = await client.post(_URL, files=_AUDIO, headers={"Origin": _SITE})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.headers["access-control-allow-origin"] == _SITE
    service.admit_dictation.assert_not_awaited()


async def test_before_admission_only_the_callers_address_is_counted(
    client: AsyncClient, service: MagicMock
) -> None:
    """The link's minute is the service's to spend, once the visitor is admitted
    (Codex on #2204): spent here, a stranger with no token could exhaust it."""
    del service
    app.dependency_overrides.pop(deps.limit_embed_dictation)
    with (
        patch(
            "app.services.rate_limit.embed_dictation_allowed",
            new=AsyncMock(return_value=Decision(allowed=True, retry_after_seconds=0)),
        ) as allowed,
        patch("app.services.rate_limit.embed_dictation_link_allowed", new=AsyncMock()) as link,
    ):
        response = await client.post(_URL, files=_AUDIO, headers={"Origin": _SITE})

    assert response.status_code == 200
    allowed.assert_awaited_once()
    link.assert_not_awaited()
