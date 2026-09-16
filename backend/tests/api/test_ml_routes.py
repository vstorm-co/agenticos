"""The ML service routes, over the wire.

The permission gates are proven in `test_platform_routes.py`; what is left for a
route test is the shape an integrator writes a client against - the multipart
form each service takes, the envelope each answers with, and that a refusal from
the service reaches them as this API's own error envelope rather than as
whatever the engine underneath said.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.ml_service_call import MLServiceCall
from app.main import app
from app.services.ml import parsing
from app.services.ml.facade import MLService, Transcript

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_V1 = settings.API_V1_STR
_FACADE = "app.services.ml.facade.MLService"


@pytest.fixture(autouse=True)
def caller() -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=_ORG,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )
    app.dependency_overrides[deps.get_ml_service] = lambda: MLService(_session())
    yield
    app.dependency_overrides.clear()


def _session() -> MagicMock:
    """A session double whose transaction verbs can be awaited.

    The refusal path commits deliberately, so a plain `MagicMock` would fail on
    the await rather than on the thing under test.
    """
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _document() -> parsing.ParsedDocument:
    return parsing.ParsedDocument(
        filename="notes.pdf",
        filetype="pdf",
        byte_size=4,
        content_hash="abc",
        pages=(parsing.ParsedPage(page_num=1, content="a page of text"),),
        chunks=("a page of text",),
    )


def _call_row(**overrides: object) -> MLServiceCall:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": _ORG,
        "service": "ocr",
        "status": "succeeded",
        "input_bytes": 2048,
        "units": 4,
        "unit": "pages",
        "duration_ms": 1200,
        "created_at": datetime(2026, 9, 16, tzinfo=UTC),
    }
    return MLServiceCall(**{**fields, **overrides})


async def test_the_catalog_answers_with_every_family_and_its_state(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{_V1}/ml/services")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(body["items"])
    served = {item["id"]: item for item in body["items"] if item["state"] == "served"}
    assert served["ocr"]["endpoint"] == "POST /api/v1/ml/documents/ocr"
    assert all(item["engine"] for item in body["items"])


async def test_analysis_takes_a_file_and_answers_with_pages_and_chunks(
    client: AsyncClient,
) -> None:
    with patch(f"{_FACADE}.analyze_document", new=AsyncMock(return_value=_document())) as called:
        response = await client.post(
            f"{_V1}/ml/documents/analyze",
            files={"file": ("notes.pdf", b"%PDF", "application/pdf")},
            data={"parser": "pymupdf", "chunk_size": "700"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["pages"] == [{"page_num": 1, "content": "a page of text"}]
    assert body["chunks"] == ["a page of text"]
    assert called.await_args.kwargs["parser"] == "pymupdf"
    assert called.await_args.kwargs["chunk_size"] == 700


async def test_a_parser_outside_the_offering_never_reaches_the_service(
    client: AsyncClient,
) -> None:
    """The contract names the two parsers, so a third is refused at the door."""
    response = await client.post(
        f"{_V1}/ml/documents/analyze",
        files={"file": ("notes.pdf", b"%PDF", "application/pdf")},
        data={"parser": "llamaparse"},
    )

    assert response.status_code == 422


async def test_recognition_passes_the_language_and_the_named_server_through(
    client: AsyncClient,
) -> None:
    server = uuid.uuid4()
    with patch(f"{_FACADE}.recognise_document", new=AsyncMock(return_value=_document())) as called:
        response = await client.post(
            f"{_V1}/ml/documents/ocr",
            files={"file": ("scan.pdf", b"%PDF", "application/pdf")},
            data={"language": "pol", "ocr_service_id": str(server)},
        )

    assert response.status_code == 200
    assert called.await_args.kwargs["language"] == "pol"
    assert called.await_args.kwargs["ocr_service_id"] == server


async def test_recognition_defaults_to_the_bundled_engine_and_english(
    client: AsyncClient,
) -> None:
    with patch(f"{_FACADE}.recognise_document", new=AsyncMock(return_value=_document())) as called:
        await client.post(
            f"{_V1}/ml/documents/ocr",
            files={"file": ("scan.pdf", b"%PDF", "application/pdf")},
        )

    assert called.await_args.kwargs["language"] == "eng"
    assert called.await_args.kwargs["ocr_service_id"] is None


async def test_a_transcription_answers_with_the_text_and_the_engine_that_read_it(
    client: AsyncClient,
) -> None:
    transcript = Transcript(text="hello there", provider="openai", model="whisper-1")
    with patch(f"{_FACADE}.transcribe", new=AsyncMock(return_value=transcript)) as called:
        response = await client.post(
            f"{_V1}/ml/audio/transcriptions",
            files={"file": ("voice.ogg", b"audio", "audio/ogg")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "text": "hello there",
        "provider": "openai",
        "model": "whisper-1",
    }
    assert called.await_args.kwargs["mime_type"] == "audio/ogg"


async def test_a_scan_answers_with_the_counts_and_the_redacted_text(
    client: AsyncClient,
) -> None:
    """The one service reached end to end here: no engine, so nothing to stub."""
    with patch("app.services.ml.facade.ml_service_call_repo.record", new=AsyncMock()):
        response = await client.post(
            f"{_V1}/ml/privacy/pii",
            json={"text": "write to ada@example.com", "categories": ["email"]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == [{"category": "email", "count": 1}]
    assert body["total"] == 1
    assert body["redacted_text"] == "write to [redacted:email]"


async def test_a_refused_scan_answers_in_this_apis_own_error_envelope(
    client: AsyncClient,
) -> None:
    response = await client.post(
        f"{_V1}/ml/privacy/pii", json={"text": "hello", "categories": ["shoe_size"]}
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"][0]["field"] == "categories"


async def test_empty_text_never_reaches_the_detectors(client: AsyncClient) -> None:
    response = await client.post(f"{_V1}/ml/privacy/pii", json={"text": ""})

    assert response.status_code == 422


async def test_the_call_log_pages_and_can_be_narrowed_to_one_service(
    client: AsyncClient,
) -> None:
    with patch(f"{_FACADE}.call_records", new=AsyncMock(return_value=([_call_row()], 1))) as called:
        response = await client.get(f"{_V1}/ml/calls?ml_service=ocr&limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["unit"] == "pages"
    assert called.await_args.kwargs == {"service": "ocr", "skip": 0, "limit": 5}


async def test_one_call_record_reads_back_without_any_of_what_was_submitted(
    client: AsyncClient,
) -> None:
    row = _call_row(status="failed", failure_stage="engine", failure_reason="nothing came back")
    with patch(f"{_FACADE}.call_record", new=AsyncMock(return_value=row)):
        response = await client.get(f"{_V1}/ml/calls/{row.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["failure_stage"] == "engine"
    assert set(body) == {
        "id",
        "service",
        "status",
        "failure_stage",
        "failure_reason",
        "input_bytes",
        "units",
        "unit",
        "duration_ms",
        "created_at",
        "updated_at",
    }
