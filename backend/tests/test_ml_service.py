"""The ML facade: tenant scoping, the usage record, and what each refusal says.

The engines are covered by `test_ml_parsing.py` and `test_ml_pii.py`. What is
left is everything this layer adds - that a successful call is recorded in the
caller's own transaction and a refused one on a transaction of its own, that the
record carries the organization the caller is acting in, and that the two rows
the surface reaches by id (a registered OCR server, a call record) are scoped so
that another tenant's is simply absent.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException, BadRequestError, ExternalServiceError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.services.ml import parsing
from app.services.ml.facade import MLService

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CALLER = uuid.uuid4()
_REPO = "app.services.ml.facade.ml_service_call_repo"


def _ctx() -> AuthContext:
    return AuthContext(
        user_id=_CALLER, organization_id=_ORG, role=OrgRoleName.OWNER.value, is_app_admin=False
    )


def _document(pages: int = 3) -> parsing.ParsedDocument:
    return parsing.ParsedDocument(
        filename="notes.pdf",
        filetype="pdf",
        byte_size=8,
        content_hash="abc",
        pages=tuple(
            parsing.ParsedPage(page_num=index + 1, content="text") for index in range(pages)
        ),
        chunks=("text",),
    )


@pytest.fixture
def recorded() -> Any:
    """Capture what the facade writes, without a database under it."""
    with patch(f"{_REPO}.record", new=AsyncMock()) as record:
        yield record


@pytest.fixture
def own_session() -> Any:
    """Capture the second session a failure record opens."""
    opened = MagicMock()

    @asynccontextmanager
    async def context():
        yield opened

    with patch("app.services.ml.facade.get_db_context", context):
        yield opened


async def test_a_parse_is_recorded_with_the_pages_it_produced(recorded: Any) -> None:
    service = MLService(MagicMock())
    with patch("app.services.ml.parsing.analyze", new=AsyncMock(return_value=_document())):
        await service.analyze_document(
            _ctx(),
            content=b"%PDF",
            filename="notes.pdf",
            parser="pymupdf",
            chunk_size=512,
            chunk_overlap=50,
            chunking_strategy="recursive",
        )

    written = recorded.await_args.kwargs
    assert written["organization_id"] == _ORG
    assert written["requested_by_user_id"] == _CALLER
    assert written["service"] == "document_analysis"
    assert written["status"] == "succeeded"
    assert (written["units"], written["unit"]) == (3, "pages")


async def test_a_recognition_is_recorded_under_its_own_service_id(recorded: Any) -> None:
    service = MLService(MagicMock())
    with patch("app.services.ml.parsing.recognise", new=AsyncMock(return_value=_document(1))):
        await service.recognise_document(
            _ctx(), content=b"%PDF", filename="scan.pdf", language="eng", ocr_service_id=None
        )

    assert recorded.await_args.kwargs["service"] == "ocr"


async def test_a_scan_is_recorded_in_the_characters_it_read(recorded: Any) -> None:
    service = MLService(MagicMock())
    await service.detect_personal_data(_ctx(), text="ada@example.com", categories=None)

    written = recorded.await_args.kwargs
    assert written["service"] == "pii_detection"
    assert (written["units"], written["unit"]) == (15, "characters")


async def test_a_refusal_is_recorded_on_a_transaction_of_its_own(
    recorded: Any, own_session: Any
) -> None:
    """A row written into the caller's transaction would roll back with the refusal."""
    service = MLService(MagicMock())
    with pytest.raises(BadRequestError):
        await service.detect_personal_data(_ctx(), text="x", categories=["shoe_size"])

    assert recorded.await_args.args[0] is own_session
    written = recorded.await_args.kwargs
    assert written["status"] == "failed"
    assert written["service"] == "pii_detection"
    assert written["units"] == 0


async def test_a_refusal_records_the_stage_the_refusing_error_named(
    recorded: Any, own_session: Any
) -> None:
    del own_session
    service = MLService(MagicMock())
    failure = ExternalServiceError(message="the engine gave way", details={"stage": "parse"})
    with (
        patch("app.services.ml.parsing.analyze", new=AsyncMock(side_effect=failure)),
        pytest.raises(ExternalServiceError),
    ):
        await service.analyze_document(
            _ctx(),
            content=b"%PDF",
            filename="notes.pdf",
            parser="pymupdf",
            chunk_size=512,
            chunk_overlap=50,
            chunking_strategy="recursive",
        )

    assert recorded.await_args.kwargs["failure_stage"] == "parse"
    assert recorded.await_args.kwargs["failure_reason"] == "the engine gave way"


async def test_a_refusal_with_no_stage_is_recorded_as_the_callers_input(
    recorded: Any, own_session: Any
) -> None:
    del own_session
    service = MLService(MagicMock())
    with (
        patch(
            "app.services.ml.parsing.analyze",
            new=AsyncMock(side_effect=AppException(message="nope")),
        ),
        pytest.raises(AppException),
    ):
        await service.analyze_document(
            _ctx(),
            content=b"%PDF",
            filename="notes.pdf",
            parser="pymupdf",
            chunk_size=512,
            chunk_overlap=50,
            chunking_strategy="recursive",
        )

    assert recorded.await_args.kwargs["failure_stage"] == "input"


async def test_a_failure_to_record_a_failure_does_not_replace_the_refusal() -> None:
    """The caller is owed the refusal that happened, not a 500 from the bookkeeping."""
    service = MLService(MagicMock())
    with (
        patch(f"{_REPO}.record", new=AsyncMock(side_effect=RuntimeError("no database"))),
        pytest.raises(BadRequestError),
    ):
        await service.detect_personal_data(_ctx(), text="x", categories=["shoe_size"])


async def test_a_submission_over_the_ceiling_is_refused_on_the_file(
    recorded: Any, own_session: Any
) -> None:
    del own_session
    service = MLService(MagicMock())
    with (
        patch("app.services.ml.facade.settings.ML_MAX_UPLOAD_SIZE_MB", 0),
        pytest.raises(BadRequestError) as caught,
    ):
        await service.analyze_document(
            _ctx(),
            content=b"x",
            filename="notes.pdf",
            parser="pymupdf",
            chunk_size=512,
            chunk_overlap=50,
            chunking_strategy="recursive",
        )

    assert caught.value.details["fields"][0]["field"] == "file"
    assert recorded.await_args.kwargs["status"] == "failed"


async def test_an_over_large_recording_is_refused_before_the_engine_is_called(
    recorded: Any, own_session: Any
) -> None:
    del own_session, recorded
    service = MLService(MagicMock())
    with (
        patch("app.services.ml.facade.settings.ML_MAX_UPLOAD_SIZE_MB", 0),
        pytest.raises(BadRequestError),
    ):
        await service.transcribe(
            _ctx(),
            content=b"x",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
        )


async def test_an_over_large_scan_is_refused_too(recorded: Any, own_session: Any) -> None:
    del own_session, recorded
    service = MLService(MagicMock())
    with (
        patch("app.services.ml.facade.settings.ML_MAX_UPLOAD_SIZE_MB", 0),
        pytest.raises(BadRequestError),
    ):
        await service.recognise_document(
            _ctx(), content=b"x", filename="scan.pdf", language="eng", ocr_service_id=None
        )


# -- the OCR server a caller may name -----------------------------------------


def _ocr_row(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "kind": "ocr",
        "is_active": True,
        "base_url": "http://ocr:8000",
    }
    return SimpleNamespace(**{**fields, **overrides})


async def test_naming_an_ocr_server_sends_the_pages_to_its_address(recorded: Any) -> None:
    del recorded
    service = MLService(MagicMock())
    with (
        patch(
            "app.services.ml.facade.LocalServiceService.get_visible",
            new=AsyncMock(return_value=_ocr_row()),
        ),
        patch(
            "app.services.ml.parsing.recognise", new=AsyncMock(return_value=_document(1))
        ) as recognise,
        patch(f"{_REPO}.record", new=AsyncMock()),
    ):
        await service.recognise_document(
            _ctx(),
            content=b"%PDF",
            filename="scan.pdf",
            language="eng",
            ocr_service_id=uuid.uuid4(),
        )

    assert recognise.await_args.kwargs["ocr_server_url"] == "http://ocr:8000"


async def test_a_service_registered_for_something_else_is_refused(own_session: Any) -> None:
    del own_session
    service = MLService(MagicMock())
    with (
        patch(
            "app.services.ml.facade.LocalServiceService.get_visible",
            new=AsyncMock(return_value=_ocr_row(kind="embedding")),
        ),
        patch(f"{_REPO}.record", new=AsyncMock()),
        pytest.raises(BadRequestError) as caught,
    ):
        await service.recognise_document(
            _ctx(),
            content=b"%PDF",
            filename="scan.pdf",
            language="eng",
            ocr_service_id=uuid.uuid4(),
        )

    assert caught.value.details["fields"][0]["field"] == "ocr_service_id"


async def test_an_ocr_server_that_is_turned_off_is_refused(own_session: Any) -> None:
    del own_session
    service = MLService(MagicMock())
    with (
        patch(
            "app.services.ml.facade.LocalServiceService.get_visible",
            new=AsyncMock(return_value=_ocr_row(is_active=False)),
        ),
        patch(f"{_REPO}.record", new=AsyncMock()),
        pytest.raises(BadRequestError) as caught,
    ):
        await service.recognise_document(
            _ctx(),
            content=b"%PDF",
            filename="scan.pdf",
            language="eng",
            ocr_service_id=uuid.uuid4(),
        )

    assert "turned off" in caught.value.details["fields"][0]["message"]


@pytest.mark.security
async def test_another_tenants_ocr_server_is_not_found(own_session: Any) -> None:
    """The scoping is the local-service layer's, reached rather than re-implemented."""
    del own_session
    service = MLService(MagicMock())
    with (
        patch(
            "app.services.ml.facade.LocalServiceService.get_visible",
            new=AsyncMock(side_effect=NotFoundError(message="Local service not found")),
        ),
        patch(f"{_REPO}.record", new=AsyncMock()),
        pytest.raises(NotFoundError),
    ):
        await service.recognise_document(
            _ctx(),
            content=b"%PDF",
            filename="scan.pdf",
            language="eng",
            ocr_service_id=uuid.uuid4(),
        )


# -- transcription -------------------------------------------------------------


async def test_a_recording_is_transcribed_and_recorded(recorded: Any) -> None:
    service = MLService(MagicMock())
    with (
        patch(
            "app.services.ml.facade.speech_to_text.default_choice",
            return_value=("openai", "whisper-1"),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value="hello there"),
        ),
    ):
        transcript = await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
        )

    assert transcript.text == "hello there"
    assert (transcript.provider, transcript.model) == ("openai", "whisper-1")
    written = recorded.await_args.kwargs
    assert written["service"] == "speech_to_text"
    assert (written["units"], written["unit"]) == (11, "characters")


async def test_a_pair_named_by_the_caller_is_checked_against_the_catalog(
    recorded: Any,
) -> None:
    """A caller who names both is taken at their word once the catalog agrees."""
    del recorded
    service = MLService(MagicMock())
    with (
        patch("app.services.ml.facade.speech_to_text.is_offered", return_value=True),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value="hello"),
        ),
        patch(f"{_REPO}.record", new=AsyncMock()),
    ):
        transcript = await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider="groq",
            model="whisper-large-v3",
        )

    assert (transcript.provider, transcript.model) == ("groq", "whisper-large-v3")


async def test_a_provider_and_model_the_catalog_does_not_offer_is_refused(
    own_session: Any,
) -> None:
    del own_session
    service = MLService(MagicMock())
    with (
        patch("app.services.ml.facade.speech_to_text.is_offered", return_value=False),
        patch(f"{_REPO}.record", new=AsyncMock()),
        pytest.raises(BadRequestError) as caught,
    ):
        await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider="openai",
            model="whisper-9",
        )

    assert caught.value.details["fields"][0]["field"] == "model"


async def test_a_deployment_that_offers_no_transcription_says_so(own_session: Any) -> None:
    del own_session
    service = MLService(MagicMock())
    with (
        patch("app.services.ml.facade.speech_to_text.default_choice", return_value=None),
        patch(f"{_REPO}.record", new=AsyncMock()),
        pytest.raises(BadRequestError) as caught,
    ):
        await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
        )

    assert caught.value.details["fields"][0]["field"] == "provider"


async def test_an_engine_that_answers_with_nothing_is_a_503_naming_the_credential(
    own_session: Any,
) -> None:
    """The client's own words never reach the caller - a provider error carries a URL."""
    del own_session
    service = MLService(MagicMock())
    with (
        patch(
            "app.services.ml.facade.speech_to_text.default_choice",
            return_value=("openai", "whisper-1"),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=None),
        ),
        patch(f"{_REPO}.record", new=AsyncMock()),
        pytest.raises(ExternalServiceError) as caught,
    ):
        await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
        )

    assert "credential" in caught.value.message
    assert caught.value.details["stage"] == "engine"


# -- reading the log back ------------------------------------------------------


@pytest.mark.security
async def test_a_call_record_from_another_tenant_reads_as_absent() -> None:
    service = MLService(MagicMock())
    with (
        patch(f"{_REPO}.get", new=AsyncMock(return_value=None)),
        pytest.raises(NotFoundError),
    ):
        await service.call_record(_ctx(), uuid.uuid4())


async def test_a_call_record_is_looked_up_inside_the_callers_organization() -> None:
    row = SimpleNamespace(id=uuid.uuid4())
    service = MLService(MagicMock())
    with patch(f"{_REPO}.get", new=AsyncMock(return_value=row)) as get:
        found = await service.call_record(_ctx(), row.id)

    assert found is row
    assert get.await_args.kwargs["organization_id"] == _ORG


async def test_the_listing_pages_and_counts_inside_the_organization() -> None:
    rows = [SimpleNamespace(id=uuid.uuid4())]
    service = MLService(MagicMock())
    with (
        patch(f"{_REPO}.list_for", new=AsyncMock(return_value=rows)) as listed,
        patch(f"{_REPO}.count_for", new=AsyncMock(return_value=7)) as counted,
    ):
        found, total = await service.call_records(_ctx(), service="ocr", skip=10, limit=5)

    assert (found, total) == (rows, 7)
    assert listed.await_args.kwargs == {
        "organization_id": _ORG,
        "service": "ocr",
        "skip": 10,
        "limit": 5,
    }
    assert counted.await_args.kwargs == {"organization_id": _ORG, "service": "ocr"}


def test_the_catalog_is_reachable_without_a_database() -> None:
    assert MLService(MagicMock()).catalog()
