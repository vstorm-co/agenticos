"""The ML facade: tenant scoping, the usage record, and what each refusal says.

The engines are covered by `test_ml_parsing.py` and `test_ml_pii.py`. What is
left is everything this layer adds - that a successful call is recorded in the
caller's own transaction and a refused one committed before that transaction
rolls back, that the record carries the organization the caller is acting in,
and that the two rows the surface reaches by id (a registered OCR server, a call
record) are scoped so that another tenant's is simply absent.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    ConfigurationError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.repositories.ml_service_call import CallFilters
from app.services.ml import parsing
from app.services.ml import pcm_wav as pcm
from app.services.ml.facade import (
    DICTATION_BYTES_PER_SECOND,
    DICTATION_GRACE_SECONDS,
    DICTATION_HEADER_ALLOWANCE,
    MLService,
)
from app.services.transcription import TranscriptionResult
from app.services.transcription_usage import TranscriptionCall
from tests.recordings import ogg_opus, pcm_wav, wav, wav_chunk, wav_fmt

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CALLER = uuid.uuid4()
_ORG_KEY = uuid.uuid4()
_REPO = "app.services.ml.facade.ml_service_call_repo"
_CALLER_KEY = uuid.uuid4()
_KEY_CHECK = "app.services.ml.facade.SpeechToTextSettingsService.key_problem"


def _heard(text: str, seconds: float | None = None) -> TranscriptionResult:
    """What the transcription client answers: the words, and a length if the provider gave one."""
    return TranscriptionResult(text=text, audio_seconds=seconds)


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


@pytest.fixture(autouse=True)
def api_org() -> Any:
    """The caller's organization: a default pair of `openai`/`whisper-1` and its key.

    A test about dictation patches the organization it needs over this one.
    """
    with patch(
        "app.repositories.organization.get_by_id",
        new=AsyncMock(
            return_value=SimpleNamespace(
                speech_to_text_provider="openai",
                speech_to_text_model="whisper-1",
                speech_to_text_secret_id=_ORG_KEY,
            )
        ),
    ) as get:
        yield get


def _db() -> MagicMock:
    """A session double whose transaction verbs can be awaited.

    `commit` is not decoration here: the failure path commits deliberately, and a
    double that cannot be awaited would let a regression in that path pass.
    """
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


async def test_a_parse_is_recorded_with_the_pages_it_produced(recorded: Any) -> None:
    service = MLService(_db())
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
    service = MLService(_db())
    with patch("app.services.ml.parsing.recognise", new=AsyncMock(return_value=_document(1))):
        await service.recognise_document(
            _ctx(), content=b"%PDF", filename="scan.pdf", language="eng", ocr_service_id=None
        )

    assert recorded.await_args.kwargs["service"] == "ocr"


async def test_a_scan_is_recorded_in_the_characters_it_read(recorded: Any) -> None:
    service = MLService(_db())
    await service.detect_personal_data(_ctx(), text="ada@example.com", categories=None)

    written = recorded.await_args.kwargs
    assert written["service"] == "pii_detection"
    assert (written["units"], written["unit"]) == (15, "characters")


async def test_a_refusal_is_recorded_and_committed_before_it_unwinds(
    recorded: Any,
) -> None:
    """A row merely added to the caller's transaction rolls back with the refusal.

    And it is written on the request's own session: a second one would check out
    a second connection while the first is still held, so a burst of refusals
    would queue on a pool its own callers are holding.
    """
    session = _db()
    service = MLService(session)
    with pytest.raises(BadRequestError):
        await service.detect_personal_data(_ctx(), text="x", categories=["shoe_size"])

    assert recorded.await_args.args[0] is session
    session.commit.assert_awaited_once()
    written = recorded.await_args.kwargs
    assert written["status"] == "failed"
    assert written["service"] == "pii_detection"
    assert written["units"] == 0


async def test_a_refusal_records_the_stage_the_refusing_error_named(recorded: Any) -> None:
    service = MLService(_db())
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


async def test_a_refusal_with_no_stage_is_recorded_as_the_callers_input(recorded: Any) -> None:
    service = MLService(_db())
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
    service = MLService(_db())
    with (
        patch(f"{_REPO}.record", new=AsyncMock(side_effect=RuntimeError("no database"))),
        pytest.raises(BadRequestError),
    ):
        await service.detect_personal_data(_ctx(), text="x", categories=["shoe_size"])


async def test_a_submission_over_the_ceiling_is_refused_on_the_file(recorded: Any) -> None:
    service = MLService(_db())
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
    recorded: Any,
) -> None:
    del recorded
    service = MLService(_db())
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


async def test_an_over_large_scan_is_refused_too(recorded: Any) -> None:
    del recorded
    service = MLService(_db())
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
    service = MLService(_db())
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


async def test_a_service_registered_for_something_else_is_refused() -> None:
    service = MLService(_db())
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


async def test_an_ocr_server_that_is_turned_off_is_refused() -> None:
    service = MLService(_db())
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
async def test_another_tenants_ocr_server_is_not_found() -> None:
    """The scoping is the local-service layer's, reached rather than re-implemented."""
    service = MLService(_db())
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
    """Naming nothing takes the organization's default pair and its key."""
    service = MLService(_db())
    with (
        patch(
            "app.services.ml.facade.speech_to_text.default_choice",
            return_value=("groq", "whisper-large-v3"),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("hello there", 2.2)),
        ) as transcribe,
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
    assert written["requested_by_user_id"] == _CALLER
    # Seconds of audio, rounded up: a 2.2-second recording is never one of 2.
    assert (written["units"], written["unit"], written["audio_ms"]) == (3, "seconds", 2200)
    assert (written["surface"], written["provider"], written["model"]) == (
        "api",
        "openai",
        "whisper-1",
    )
    assert written["agent_id"] is None
    assert written["channel_bot_id"] is None
    assert written["secret_id"] == _ORG_KEY
    sent = transcribe.await_args.kwargs
    assert (sent["secret_id"], sent["shared_key"]) == (_ORG_KEY, True)


async def test_a_recording_with_no_stated_length_counts_zero_seconds(recorded: Any) -> None:
    """`gpt-4o-transcribe` gives no length: the row says seconds and leaves the
    length null, so a summary counts it as unmeasured rather than as silence."""
    service = MLService(_db())
    with (
        patch(
            "app.services.ml.facade.speech_to_text.default_choice",
            return_value=("openai", "gpt-4o-transcribe"),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("hello there")),
        ),
    ):
        await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
        )

    written = recorded.await_args.kwargs
    assert (written["units"], written["unit"], written["audio_ms"]) == (0, "seconds", None)


async def test_a_pair_named_by_the_caller_is_checked_against_the_catalog(
    recorded: Any,
) -> None:
    """A caller who names both is taken at their word once the catalog agrees."""
    del recorded
    service = MLService(_db())
    offered = SimpleNamespace(models=(SimpleNamespace(id="whisper-large-v3"),))
    with (
        patch("app.services.ml.facade.speech_to_text.by_provider", return_value=offered),
        patch("app.services.ml.facade.speech_to_text.is_offered", return_value=True),
        patch(f"{_KEY_CHECK}", new=AsyncMock(return_value=None)) as checked,
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("hello")),
        ) as transcribe,
        patch(f"{_REPO}.record", new=AsyncMock()),
    ):
        transcript = await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider="groq",
            model="whisper-large-v3",
            secret_id=_CALLER_KEY,
        )

    assert (transcript.provider, transcript.model) == ("groq", "whisper-large-v3")
    # Checked as an agent's key is - the caller has to be able to view it.
    assert checked.await_args.kwargs["provider"] == "groq"
    assert checked.await_args.kwargs["ctx"] is not None
    sent = transcribe.await_args.kwargs
    assert (sent["secret_id"], sent["shared_key"]) == (_CALLER_KEY, False)


async def test_naming_only_a_provider_uses_that_providers_first_model() -> None:
    """Falling back to the deployment default would send the audio elsewhere.

    A caller who named `groq` and left the model open chose the engine; the
    default pair is a different engine, and on this surface that can mean a
    vendor rather than the self-hosted server they configured.
    """
    offered = SimpleNamespace(models=(SimpleNamespace(id="whisper-large-v3"),))
    service = MLService(_db())
    with (
        patch("app.services.ml.facade.speech_to_text.by_provider", return_value=offered),
        patch(
            "app.services.ml.facade.speech_to_text.default_choice",
            return_value=("openai", "whisper-1"),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("hello")),
        ),
        patch(f"{_KEY_CHECK}", new=AsyncMock(return_value=None)),
        patch(f"{_REPO}.record", new=AsyncMock()),
    ):
        transcript = await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider="groq",
            model=None,
            secret_id=_CALLER_KEY,
        )

    assert (transcript.provider, transcript.model) == ("groq", "whisper-large-v3")


async def test_naming_only_a_model_is_refused_because_two_providers_can_offer_it() -> None:
    service = MLService(_db())
    with (
        patch(f"{_REPO}.record", new=AsyncMock()),
        pytest.raises(BadRequestError) as caught,
    ):
        await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model="whisper-1",
        )

    assert caught.value.details["fields"][0]["field"] == "provider"


async def test_a_provider_that_does_not_transcribe_here_is_refused() -> None:
    service = MLService(_db())
    with (
        patch("app.services.ml.facade.speech_to_text.by_provider", return_value=None),
        patch(f"{_REPO}.record", new=AsyncMock()),
        pytest.raises(BadRequestError) as caught,
    ):
        await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider="telepathy",
            model=None,
        )

    assert caught.value.details["fields"][0]["field"] == "provider"


async def test_a_recording_is_held_to_the_transcription_clients_own_ceiling() -> None:
    """Raising the ML ceiling above 25 MB must not make the client answer 503 about a key."""
    service = MLService(_db())
    with (
        patch("app.services.ml.facade.settings.ML_MAX_UPLOAD_SIZE_MB", 4096),
        patch("app.services.ml.facade.transcription.MAX_BYTES", 8),
        patch(f"{_REPO}.record", new=AsyncMock()),
        pytest.raises(BadRequestError) as caught,
    ):
        await service.transcribe(
            _ctx(),
            content=b"x" * 9,
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
        )

    assert caught.value.details["fields"][0]["field"] == "file"


async def test_a_provider_and_model_the_catalog_does_not_offer_is_refused() -> None:
    service = MLService(_db())
    offered = SimpleNamespace(models=(SimpleNamespace(id="whisper-1"),))
    with (
        patch("app.services.ml.facade.speech_to_text.by_provider", return_value=offered),
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


async def test_a_deployment_that_offers_no_transcription_says_so(api_org: AsyncMock) -> None:
    api_org.return_value = SimpleNamespace(
        speech_to_text_provider=None, speech_to_text_model=None, speech_to_text_secret_id=None
    )
    service = MLService(_db())
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


async def test_an_engine_failure_is_recorded_and_re_raised(recorded: Any) -> None:
    """The service's own refusal reaches the caller unchanged, and the usage log
    puts it against the engine, not the caller's input."""
    service = MLService(_db())
    failure = ExternalServiceError(
        message="m", details={"reason": "provider_error", "stage": "engine"}
    )
    with (
        patch(
            "app.services.ml.facade.speech_to_text.default_choice",
            return_value=("openai", "whisper-1"),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(side_effect=failure),
        ),
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

    assert caught.value is failure
    assert recorded.await_args.kwargs["status"] == "failed"
    assert recorded.await_args.kwargs["failure_stage"] == "engine"


async def test_an_organization_with_no_default_falls_back_to_the_deployments_first(
    api_org: AsyncMock, recorded: Any
) -> None:
    """With no pair of its own, the deployment's first offered one - and the
    key has to be named, since there is no default key for it."""
    del recorded
    api_org.return_value = SimpleNamespace(
        speech_to_text_provider=None, speech_to_text_model=None, speech_to_text_secret_id=None
    )
    with (
        patch(
            "app.services.ml.facade.speech_to_text.default_choice",
            return_value=("groq", "whisper-large-v3"),
        ),
        patch(f"{_KEY_CHECK}", new=AsyncMock(return_value=None)),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("hi")),
        ) as transcribe,
    ):
        transcript = await MLService(_db()).transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
            secret_id=_CALLER_KEY,
        )

    assert (transcript.provider, transcript.model) == ("groq", "whisper-large-v3")
    assert transcribe.await_args.kwargs["secret_id"] == _CALLER_KEY


async def test_another_provider_with_no_key_named_is_not_configured(recorded: Any) -> None:
    """The organization's key is for the provider it was chosen beside, and
    never carries over to another one."""
    offered = SimpleNamespace(models=(SimpleNamespace(id="whisper-large-v3"),))
    with (
        patch("app.services.ml.facade.speech_to_text.by_provider", return_value=offered),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe", new=AsyncMock()
        ) as transcribe,
        pytest.raises(ConfigurationError) as caught,
    ):
        await MLService(_db()).transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider="groq",
            model=None,
        )

    assert caught.value.details["reason"] == "not_configured"
    transcribe.assert_not_awaited()
    written = recorded.await_args.kwargs
    assert (written["status"], written["secret_id"]) == ("failed", None)


async def test_an_organization_pair_whose_key_was_deleted_is_not_configured(
    api_org: AsyncMock, recorded: Any
) -> None:
    del recorded
    api_org.return_value = SimpleNamespace(
        speech_to_text_provider="openai",
        speech_to_text_model="whisper-1",
        speech_to_text_secret_id=None,
    )
    with pytest.raises(ConfigurationError) as caught:
        await MLService(_db()).transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
        )

    assert caught.value.details["reason"] == "not_configured"


async def test_a_named_key_the_caller_may_not_use_is_refused_on_its_field(
    recorded: Any,
) -> None:
    del recorded
    with (
        patch(f"{_KEY_CHECK}", new=AsyncMock(return_value="That key is not in this vault")),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe", new=AsyncMock()
        ) as transcribe,
        pytest.raises(BadRequestError) as caught,
    ):
        await MLService(_db()).transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
            secret_id=_CALLER_KEY,
        )

    assert caught.value.details["fields"][0]["field"] == "secret_id"
    transcribe.assert_not_awaited()


# -- dictation into the composer (#1797) ---------------------------------------


_AGENT = SimpleNamespace(
    id=uuid.uuid4(), organization_id=_ORG, name="Support", status="draft", current_version_id=None
)
"""An agent with nothing published, so the organization's settings answer alone."""

_SETTINGS = "app.services.speech_to_text_settings"


@pytest.fixture
def org_read() -> Any:
    """The organization `speech_to_text_settings` reads for the resolved pair."""
    with patch(
        "app.services.ml.facade.organization_repo.get_by_id",
        new=AsyncMock(return_value=_speech_org()),
    ) as get:
        yield get


@pytest.fixture(autouse=True)
def switch() -> Any:
    """The agent's published Dictation switch, on unless a test turns it off.

    It is what sends `/chat` dictation to a provider; the tests below are about
    what happens once it does. Read for real in `test_speech_to_text_settings.py`.
    """
    with patch(
        "app.services.ml.facade.SpeechToTextSettingsService.dictates_on_provider",
        new=AsyncMock(return_value=True),
    ) as on:
        yield on


@pytest.fixture(autouse=True)
def compressed() -> Any:
    """The deployment's `dictation_compressed_audio`, off unless a test turns it on."""
    with patch(
        "app.services.ml.facade.DeploymentSettingsService.accepts_compressed_dictation",
        new=AsyncMock(return_value=False),
    ) as accepts:
        yield accepts


def _published(override: dict[str, str] | None) -> tuple[SimpleNamespace, AsyncMock]:
    """An agent whose published spec carries `override`, and the version read."""
    version_id = uuid.uuid4()
    agent = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=_ORG,
        name="Support",
        status="published",
        current_version_id=version_id,
    )
    spec = (
        {"name": "Support"} if override is None else {"name": "Support", "speech_to_text": override}
    )
    return agent, AsyncMock(return_value=SimpleNamespace(id=version_id, spec=spec))


def _speech_org(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "speech_to_text_provider": "openai",
        "speech_to_text_model": "gpt-4o-transcribe",
        "speech_to_text_secret_id": _ORG_KEY,
        "speech_to_text_language": "pl",
        "dictation_max_seconds": 300,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _has_key(keyed: set[str]) -> AsyncMock:
    """`TranscriptionService.has_key` answering yes for these providers' named keys."""

    async def has_key(
        _organization_id: uuid.UUID,
        *,
        provider: str,
        secret_id: uuid.UUID | None,
        shared_key: bool,
    ) -> bool:
        del shared_key
        return secret_id is not None and provider in keyed

    return AsyncMock(side_effect=has_key)


async def test_a_dictation_is_transcribed_with_the_org_settings_and_recorded(
    recorded: Any,
) -> None:
    """The organization's pair and language, not the caller's: the person
    dictating did not choose the engine, and cannot name another one."""
    service = MLService(_db())
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ) as get,
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("dzień dobry")),
        ) as transcribe,
    ):
        text = await service.dictate(
            _ctx(), agent=_AGENT, content=pcm_wav(1.5), mime_type="audio/wav"
        )

    assert text == "dzień dobry"
    assert get.await_args.args[1] == _ORG
    sent = transcribe.await_args
    assert sent.args[0].filename == "recording.wav"
    assert sent.args[0].mime_type == "audio/wav"
    assert sent.kwargs["organization_id"] == _ORG
    assert (sent.kwargs["provider"], sent.kwargs["model"]) == ("openai", "gpt-4o-transcribe")
    assert sent.kwargs["language"] == "pl"
    assert (sent.kwargs["secret_id"], sent.kwargs["shared_key"]) == (_ORG_KEY, True)
    written = recorded.await_args.kwargs
    assert written["service"] == "speech_to_text"
    assert written["secret_id"] == _ORG_KEY
    assert (written["surface"], written["agent_id"]) == ("chat", _AGENT.id)
    assert (written["provider"], written["model"]) == ("openai", "gpt-4o-transcribe")
    assert written["requested_by_user_id"] == _CALLER
    # Counted from the samples, so exact - nobody else had to say.
    assert (written["units"], written["unit"], written["audio_ms"]) == (2, "seconds", 1500)


async def test_a_dictation_uses_the_agents_published_override(recorded: Any) -> None:
    """A Polish agent in an organization set up for another engine: the agent's
    pair and language, from the version `/chat` runs."""
    del recorded
    agent_key = uuid.uuid4()
    agent, get_version = _published(
        {
            "provider": "groq",
            "model": "whisper-large-v3",
            "language": "de",
            "secret_id": str(agent_key),
        }
    )
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(f"{_SETTINGS}.agent_repo.get_version", new=get_version),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("ok")),
        ) as transcribe,
    ):
        await MLService(_db()).dictate(
            _ctx(), agent=agent, content=pcm_wav(1), mime_type="audio/wav"
        )

    sent = transcribe.await_args.kwargs
    assert (sent["provider"], sent["model"], sent["language"]) == ("groq", "whisper-large-v3", "de")
    # The agent's own key, lent by its publisher - never the organization's.
    assert (sent["secret_id"], sent["shared_key"]) == (agent_key, False)
    assert get_version.await_args.args[1] == agent.current_version_id
    assert get_version.await_args.kwargs["organization_id"] == _ORG


async def test_an_agent_override_makes_dictation_work_where_the_org_has_no_pair(
    recorded: Any,
) -> None:
    del recorded
    agent, get_version = _published({"provider": "openai", "model": "whisper-1"})
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(
                return_value=_speech_org(speech_to_text_provider=None, speech_to_text_model=None)
            ),
        ),
        patch(f"{_SETTINGS}.agent_repo.get_version", new=get_version),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("ok")),
        ) as transcribe,
    ):
        await MLService(_db()).dictate(
            _ctx(), agent=agent, content=pcm_wav(1), mime_type="audio/wav"
        )

    assert transcribe.await_args.kwargs["model"] == "whisper-1"
    # The organization's language still applies where the agent pins none.
    assert transcribe.await_args.kwargs["language"] == "pl"


@pytest.mark.parametrize(
    ("org", "agent_override", "keyed", "ready", "provider", "unavailable"),
    [
        (_speech_org(), None, {"openai"}, True, "openai", None),
        (_speech_org(), None, set(), False, "openai", "no_key"),
        (
            _speech_org(speech_to_text_model="withdrawn"),
            None,
            {"openai"},
            False,
            "openai",
            "not_offered",
        ),
        (
            _speech_org(speech_to_text_provider=None, speech_to_text_model=None),
            None,
            {"openai"},
            False,
            None,
            "no_provider",
        ),
        (
            _speech_org(speech_to_text_provider=None, speech_to_text_model=None),
            {"provider": "mistral", "model": "voxtral-mini-latest", "secret_id": str(_ORG_KEY)},
            {"mistral"},
            True,
            "mistral",
            None,
        ),
        (
            _speech_org(),
            {"provider": "mistral", "model": "voxtral-mini-latest"},
            {"openai"},
            False,
            "mistral",
            "no_key",
        ),
        (_speech_org(), {"language": "de"}, {"openai"}, True, "openai", None),
    ],
    ids=[
        "org-pair",
        "no-key",
        "withdrawn-model",
        "no-pair",
        "agent-pair-without-org-pair",
        "agent-pair-without-its-key",
        "language-only-keeps-the-org-key",
    ],
)
async def test_dictation_readiness_follows_the_resolved_pair(
    org: SimpleNamespace,
    agent_override: dict[str, str] | None,
    keyed: set[str],
    ready: bool,
    provider: str | None,
    unavailable: str | None,
) -> None:
    """The provider dictates once the agent's switch is on and a pair resolves for
    it, the catalog still offers it and a usable key is named beside it. The provider is
    returned regardless, because the composer records in its format, and
    `unavailable` says which of the three is missing."""
    agent, get_version = _published(agent_override)
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id", new=AsyncMock(return_value=org)
        ),
        patch(f"{_SETTINGS}.agent_repo.get_version", new=get_version),
        patch(
            "app.services.ml.facade.TranscriptionService.has_key",
            new=_has_key(keyed),
        ),
    ):
        status = await MLService(_db()).dictation_status(_ctx(), agent=agent)

    assert (status.engine == "server", status.provider, status.unavailable) == (
        ready,
        provider,
        unavailable,
    )
    assert status.requested
    assert status.max_seconds == org.dictation_max_seconds


async def test_with_the_agents_switch_off_the_composer_dictates_in_the_browser(
    switch: AsyncMock,
) -> None:
    """Free and always there: the provider is used only when the agent asks for it."""
    switch.return_value = False
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch("app.services.ml.facade.TranscriptionService.has_key", new=_has_key({"openai"})),
    ):
        status = await MLService(_db()).dictation_status(_ctx(), agent=_AGENT)

    assert (status.engine, status.requested, status.server_available) == ("browser", False, True)


async def test_the_embed_form_learns_availability_without_the_agents_switch(
    switch: AsyncMock,
) -> None:
    """A hosted page or a widget on `server` is not gated by the agent's `/chat`
    switch, so the form asks `server_available` - and the format is the catalog's."""
    switch.return_value = False
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(
                return_value=_speech_org(
                    speech_to_text_provider="mistral",
                    speech_to_text_model="voxtral-mini-latest",
                )
            ),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.has_key",
            new=_has_key({"mistral"}),
        ),
    ):
        status = await MLService(_db()).dictation_status(_ctx(), agent=_AGENT)

    assert (status.engine, status.server_available, status.format) == ("browser", True, "wav")


@pytest.mark.parametrize(
    ("provider", "model", "accepts_compressed", "recorded_as"),
    [
        ("openai", "gpt-4o-transcribe", False, "wav"),
        ("openai", "gpt-4o-transcribe", True, "webm"),
        ("mistral", "voxtral-mini-latest", True, "wav"),
        ("mistral", "voxtral-mini-latest", False, "wav"),
    ],
    ids=["pcm-by-default", "compressed-unlocked", "mistral-unlocked", "mistral"],
)
async def test_the_format_a_browser_records_in_follows_the_deployment_and_the_catalog(
    compressed: AsyncMock, provider: str, model: str, accepts_compressed: bool, recorded_as: str
) -> None:
    """WAV unless the deployment accepts compressed audio and the provider
    takes what `MediaRecorder` makes - one answer, for every client."""
    compressed.return_value = accepts_compressed
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(
                return_value=_speech_org(
                    speech_to_text_provider=provider, speech_to_text_model=model
                )
            ),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.has_key",
            new=_has_key({provider}),
        ),
    ):
        status = await MLService(_db()).dictation_status(_ctx(), agent=_AGENT)
        server = await MLService(_db()).server_dictation(_AGENT)

    assert status.format == server.format == recorded_as


async def test_a_visitors_dictation_is_recorded_against_its_surface_and_no_person(
    recorded: Any,
) -> None:
    """The ctx-free core the hosted page and the widget call: the caller states
    the attribution, and nobody is named as having asked."""
    call = TranscriptionCall(
        organization_id=_ORG, surface="widget", provider=None, model=None, agent_id=_AGENT.id
    )
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("hello")),
        ) as transcribe,
    ):
        text = await MLService(_db()).transcribe_dictation(
            call,
            organization=_speech_org(),
            agent=_AGENT,
            content=pcm_wav(1.25),
            mime_type="audio/wav",
            accept_unmeasured=False,
        )

    assert text == "hello"
    assert transcribe.await_args.kwargs["organization_id"] == _ORG
    written = recorded.await_args.kwargs
    assert (written["surface"], written["agent_id"]) == ("widget", _AGENT.id)
    assert written["requested_by_user_id"] is None
    assert (written["provider"], written["model"]) == ("openai", "gpt-4o-transcribe")
    assert written["audio_ms"] == 1250


async def test_a_visitors_recording_of_unknown_length_is_refused_before_the_provider(
    recorded: Any, compressed: AsyncMock
) -> None:
    """On a public surface nothing but the length bounds a stranger's spend, so a
    compressed recording whose length cannot be read is not sent to be paid for."""
    compressed.return_value = True
    call = TranscriptionCall(organization_id=_ORG, surface="hosted", provider=None, model=None)
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe", new=AsyncMock()
        ) as transcribe,
        pytest.raises(BadRequestError) as refused,
    ):
        await MLService(_db()).transcribe_dictation(
            call,
            organization=_speech_org(),
            agent=_AGENT,
            content=b"not a container",
            mime_type="audio/webm",
            accept_unmeasured=False,
        )

    assert refused.value.details is not None
    assert refused.value.details["reason"] == "unsupported_type"
    transcribe.assert_not_awaited()
    assert recorded.await_args.kwargs["status"] == "failed"


async def test_a_members_recording_of_unknown_length_is_accepted_under_the_byte_cap(
    recorded: Any, compressed: AsyncMock
) -> None:
    del recorded
    compressed.return_value = True
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("ok")),
        ) as transcribe,
    ):
        text = await MLService(_db()).dictate(
            _ctx(), agent=_AGENT, content=b"not a container", mime_type="audio/webm"
        )

    assert text == "ok"
    transcribe.assert_awaited_once()


@pytest.mark.parametrize("accept_unmeasured", [True, False], ids=["console", "embed"])
async def test_a_recording_measured_over_the_limit_is_refused_before_the_provider(
    recorded: Any, compressed: AsyncMock, accept_unmeasured: bool
) -> None:
    """Low-bitrate Opus: far under the byte cap, far over the length. Where
    compressed audio is accepted, the length its header states refuses it on
    every surface, and says what the limit is."""
    compressed.return_value = True
    recording = ogg_opus(10 + DICTATION_GRACE_SECONDS + 1)
    assert len(recording) < 10 * DICTATION_BYTES_PER_SECOND
    call = TranscriptionCall(organization_id=_ORG, surface="chat", provider=None, model=None)
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe", new=AsyncMock()
        ) as transcribe,
        pytest.raises(BadRequestError) as refused,
    ):
        await MLService(_db()).transcribe_dictation(
            call,
            organization=_speech_org(dictation_max_seconds=10),
            agent=_AGENT,
            content=recording,
            mime_type="audio/ogg",
            accept_unmeasured=accept_unmeasured,
        )

    assert refused.value.details is not None
    assert refused.value.details["reason"] == "too_large"
    assert refused.value.details["limit_seconds"] == 10
    transcribe.assert_not_awaited()
    assert recorded.await_args.kwargs["audio_ms"] == (10 + DICTATION_GRACE_SECONDS + 1) * 1000


async def test_a_compressed_recording_a_tick_past_the_limit_is_transcribed(
    recorded: Any, compressed: AsyncMock
) -> None:
    """The browser stops on a once-a-second tick, so a recording the limit stopped
    is a little over it - and must not be refused for that."""
    compressed.return_value = True
    call = TranscriptionCall(organization_id=_ORG, surface="widget", provider=None, model=None)
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("ok", 99.0)),
        ),
    ):
        text = await MLService(_db()).transcribe_dictation(
            call,
            organization=_speech_org(dictation_max_seconds=10),
            agent=_AGENT,
            content=ogg_opus(10.9),
            mime_type="audio/ogg",
            reported_seconds=50.0,
            accept_unmeasured=False,
        )

    assert text == "ok"
    # Measured first: ahead of the provider's figure and the browser's.
    assert recorded.await_args.kwargs["audio_ms"] == 10_900


async def test_a_shut_gate_is_not_configured_and_resolves_nothing(recorded: Any) -> None:
    call = TranscriptionCall(organization_id=_ORG, surface="hosted", provider=None, model=None)
    with (
        patch(f"{_SETTINGS}.SpeechToTextSettingsService.for_agent", new=AsyncMock()) as resolved,
        pytest.raises(ConfigurationError) as refused,
    ):
        await MLService(_db()).transcribe_dictation(
            call,
            organization=None,
            agent=_AGENT,
            content=b"a",
            mime_type="audio/webm",
            accept_unmeasured=False,
        )

    assert refused.value.details == {"reason": "not_configured"}
    resolved.assert_not_awaited()
    assert recorded.await_args.kwargs["status"] == "failed"


async def test_dictation_readiness_for_an_unpublished_agent_answers_from_the_org() -> None:
    """Never a refusal: the composer asks before the agent has anything published,
    and the organization's default is what a published switch would reach."""
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.has_key",
            new=_has_key({"openai"}),
        ),
    ):
        status = await MLService(_db()).dictation_status(_ctx(), agent=_AGENT)

    assert (status.server_available, status.provider) == (True, "openai")


async def test_an_archived_agent_is_never_ready_to_dictate_to() -> None:
    agent, get_version = _published(None)
    agent.status = "archived"
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(f"{_SETTINGS}.agent_repo.get_version", new=get_version),
        patch(
            "app.services.ml.facade.TranscriptionService.has_key",
            new=_has_key({"openai"}),
        ),
    ):
        status = await MLService(_db()).dictation_status(_ctx(), agent=agent)

    assert (status.engine, status.server_available) == ("browser", True)


async def test_a_recording_for_an_archived_agent_is_refused_before_the_provider() -> None:
    """What readiness says before the press, the dictation says after it: an
    archived agent takes no message, so nothing is paid for (review of #2138)."""
    agent, _get_version = _published(None)
    agent.status = "archived"
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id", new=AsyncMock()
        ) as organization,
        patch.object(MLService, "transcribe_dictation", new=AsyncMock()) as transcribe,
        pytest.raises(ConfigurationError) as refused,
    ):
        await MLService(_db()).dictate(_ctx(), agent=agent, content=b"RIFF", mime_type="audio/wav")

    assert refused.value.details == {"reason": "not_configured"}
    organization.assert_not_awaited()
    transcribe.assert_not_awaited()


async def test_dictation_readiness_with_no_organization_is_not_found() -> None:
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id", new=AsyncMock(return_value=None)
        ),
        pytest.raises(NotFoundError),
    ):
        await MLService(_db()).dictation_status(_ctx(), agent=_AGENT)


@pytest.mark.parametrize(
    ("org", "content", "mime", "reason"),
    [
        (None, b"a", "audio/webm", "not_configured"),
        (
            _speech_org(speech_to_text_provider=None, speech_to_text_model=None),
            b"a",
            "audio/webm",
            "not_configured",
        ),
        (_speech_org(), b"", "audio/wav", "empty"),
        (_speech_org(), b"a", "audio/mpeg", "unsupported_type"),
        (_speech_org(), ogg_opus(2), "audio/ogg", "unsupported_type"),
        (_speech_org(), b"a", "audio/webm;codecs=opus", "unsupported_type"),
        (_speech_org(), b"a", "audio/mp4", "unsupported_type"),
        (_speech_org(), pcm_wav(1, channels=2), "audio/wav", "unsupported_type"),
        (_speech_org(), pcm_wav(1, rate=48_000), "audio/wav", "unsupported_type"),
        (_speech_org(), b"not a wav", "audio/wav", "unsupported_type"),
        (_speech_org(), wav(wav_fmt(), wav_chunk(b"data", b"")), "audio/wav", "empty"),
        (
            _speech_org(dictation_max_seconds=10),
            b"x"
            * (
                (10 + DICTATION_GRACE_SECONDS) * DICTATION_BYTES_PER_SECOND
                + DICTATION_HEADER_ALLOWANCE
                + 1
            ),
            "audio/wav",
            "too_large",
        ),
    ],
    ids=[
        "no-org",
        "no-pair",
        "empty",
        "mp3",
        "ogg-while-pcm-only",
        "webm-while-pcm-only",
        "mp4-while-pcm-only",
        "stereo-wav",
        "48-khz-wav",
        "not-a-wav",
        "no-samples",
        "over-the-byte-cap",
    ],
)
async def test_a_dictation_is_refused_with_a_reason_and_the_refusal_recorded(
    recorded: Any, org: SimpleNamespace | None, content: bytes, mime: str, reason: str
) -> None:
    """Refused before the engine is paid for, and the refusal still lands in the
    usage log on a commit of its own."""
    db = _db()
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id", new=AsyncMock(return_value=org)
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe", new=AsyncMock()
        ) as transcribe,
        pytest.raises(AppException) as raised,
    ):
        await MLService(db).dictate(_ctx(), agent=_AGENT, content=content, mime_type=mime)

    assert raised.value.details is not None
    assert raised.value.details["reason"] == reason
    transcribe.assert_not_awaited()
    assert recorded.await_args.kwargs["status"] == "failed"
    db.commit.assert_awaited()


async def test_a_recording_for_an_agent_whose_switch_is_off_is_refused(
    recorded: Any, switch: AsyncMock
) -> None:
    """Off, the composer dictates in the browser; a recording posted anyway is
    refused before the provider is paid."""
    switch.return_value = False
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch("app.services.ml.facade.TranscriptionService.transcribe", new=AsyncMock()) as sent,
        pytest.raises(ConfigurationError) as refused,
    ):
        await MLService(_db()).dictate(
            _ctx(), agent=_AGENT, content=pcm_wav(1), mime_type="audio/wav"
        )

    assert refused.value.details == {"reason": "not_configured"}
    sent.assert_not_awaited()
    assert recorded.await_args.kwargs["status"] == "failed"


async def test_a_pcm_recording_at_the_limit_and_its_grace_is_transcribed(recorded: Any) -> None:
    del recorded
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org(dictation_max_seconds=10)),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("ok")),
        ),
    ):
        text = await MLService(_db()).dictate(
            _ctx(),
            agent=_AGENT,
            content=pcm_wav(10 + DICTATION_GRACE_SECONDS),
            mime_type="audio/wav",
        )

    assert text == "ok"


@pytest.mark.usefixtures("org_read")
@pytest.mark.parametrize("accept_unmeasured", [True, False], ids=["console", "embed"])
async def test_one_sample_past_the_limit_is_refused_before_the_provider(
    recorded: Any, accept_unmeasured: bool
) -> None:
    """Raw PCM's length is its size, so the limit is exact: the samples are
    counted, and the usage row says how long the refused recording was."""
    over = 10 + DICTATION_GRACE_SECONDS + 1 / 16_000
    call = TranscriptionCall(organization_id=_ORG, surface="hosted", provider=None, model=None)
    with (
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe", new=AsyncMock()
        ) as transcribe,
        pytest.raises(BadRequestError) as refused,
    ):
        await MLService(_db()).transcribe_dictation(
            call,
            organization=_speech_org(dictation_max_seconds=10),
            agent=_AGENT,
            content=pcm_wav(over),
            mime_type="audio/wav",
            accept_unmeasured=accept_unmeasured,
        )

    assert refused.value.details is not None
    assert (refused.value.details["reason"], refused.value.details["limit_seconds"]) == (
        "too_large",
        10,
    )
    transcribe.assert_not_awaited()
    assert recorded.await_args.kwargs["audio_ms"] == round(over * 1000)


async def test_the_provider_is_sent_the_counted_samples_behind_a_header_of_our_own(
    recorded: Any,
) -> None:
    """Whatever else the file carried - a chunk of metadata, a trailer - stays
    here, and the length recorded is the samples' own, whatever the provider or
    the browser says."""
    samples = bytes(range(256)) * 250
    posted = wav(
        wav_chunk(b"LIST", b"INFOsomething"),
        wav_fmt(),
        wav_chunk(b"data", samples),
        wav_chunk(b"junk", b"\xff" * 99),
    )
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("ok", 99.0)),
        ) as transcribe,
    ):
        await MLService(_db()).dictate(
            _ctx(), agent=_AGENT, content=posted, mime_type="audio/x-wav", reported_seconds=50.0
        )

    sent = transcribe.await_args.args[0]
    assert sent.content == pcm.wrap(samples)
    assert (sent.filename, sent.mime_type) == ("recording.wav", "audio/wav")
    written = recorded.await_args.kwargs
    assert written["audio_ms"] == 2000
    assert written["input_bytes"] == len(posted)


@pytest.mark.usefixtures("org_read")
@pytest.mark.parametrize("accept_unmeasured", [True, False], ids=["console", "embed"])
@pytest.mark.parametrize("mime", ["audio/webm;codecs=opus", "audio/ogg", "audio/mp4"])
async def test_compressed_audio_is_refused_until_the_deployment_accepts_it(
    recorded: Any, compressed: AsyncMock, mime: str, accept_unmeasured: bool
) -> None:
    """Off by default, on the console's route and on a public page's alike, and
    the refusal says what is accepted; on, the same recording is transcribed."""
    del recorded
    call = TranscriptionCall(organization_id=_ORG, surface="chat", provider=None, model=None)

    async def post() -> str:
        return await MLService(_db()).transcribe_dictation(
            call,
            organization=_speech_org(),
            agent=_AGENT,
            content=ogg_opus(2),
            mime_type=mime,
            accept_unmeasured=accept_unmeasured,
        )

    with patch(
        "app.services.ml.facade.TranscriptionService.transcribe",
        new=AsyncMock(return_value=_heard("ok")),
    ) as transcribe:
        with pytest.raises(BadRequestError) as refused:
            await post()
        transcribe.assert_not_awaited()
        compressed.return_value = True
        text = await post()

    assert refused.value.details is not None
    assert refused.value.details["reason"] == "unsupported_type"
    assert refused.value.details["accepted"] == ["audio/wav"]
    assert text == "ok"
    transcribe.assert_awaited_once()


@pytest.mark.usefixtures("org_read")
async def test_an_unlocked_deployment_says_it_accepts_every_type(
    recorded: Any, compressed: AsyncMock
) -> None:
    del recorded
    compressed.return_value = True
    with pytest.raises(BadRequestError) as refused:
        await MLService(_db()).transcribe_dictation(
            TranscriptionCall(organization_id=_ORG, surface="chat", provider=None, model=None),
            organization=_speech_org(),
            agent=_AGENT,
            content=b"ID3",
            mime_type="audio/mpeg",
            accept_unmeasured=True,
        )

    assert refused.value.details is not None
    assert refused.value.details["accepted"] == [
        "audio/mp4",
        "audio/ogg",
        "audio/wav",
        "audio/webm",
    ]


@pytest.mark.parametrize(
    ("mime", "filename", "sent_type"),
    [
        ("audio/webm;codecs=opus", "recording.webm", "audio/webm"),
        ("audio/ogg;codecs=opus", "recording.ogg", "audio/ogg"),
        ("audio/mp4", "recording.m4a", "audio/mp4"),
        ("audio/wav", "recording.wav", "audio/wav"),
        ("audio/x-wav", "recording.wav", "audio/wav"),
        ("Audio/Wave", "recording.wav", "audio/wav"),
    ],
)
async def test_a_dictation_is_named_for_the_format_the_provider_reads(
    recorded: Any, compressed: AsyncMock, mime: str, filename: str, sent_type: str
) -> None:
    """The provider reads the format from the file name. MP4 audio goes as
    `.m4a`, the name every OpenAI-compatible provider lists, and every name for
    WAV arrives as one type."""
    del recorded
    compressed.return_value = True
    content = pcm_wav(1) if sent_type == "audio/wav" else b"a"
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("ok")),
        ) as transcribe,
    ):
        await MLService(_db()).dictate(_ctx(), agent=_AGENT, content=content, mime_type=mime)

    sent = transcribe.await_args.args[0]
    assert (sent.filename, sent.mime_type) == (filename, sent_type)


async def test_a_wav_recording_of_the_longest_dictation_fits_under_the_cap(
    recorded: Any,
) -> None:
    """Every browser records 16 kHz mono 16-bit WAV by default: 32,000 bytes a
    second and a 44-byte header, which a full-length recording must not exceed."""
    del recorded
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org(dictation_max_seconds=300)),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("ok")),
        ) as transcribe,
    ):
        text = await MLService(_db()).dictate(
            _ctx(), agent=_AGENT, content=pcm_wav(300), mime_type="audio/wav"
        )

    assert text == "ok"
    transcribe.assert_awaited_once()


async def test_an_engine_refusal_during_dictation_is_recorded_and_re_raised(
    recorded: Any,
) -> None:
    failure = ExternalServiceError(message="m", details={"reason": "timeout", "stage": "engine"})
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(side_effect=failure),
        ),
        pytest.raises(ExternalServiceError) as caught,
    ):
        await MLService(_db()).dictate(
            _ctx(), agent=_AGENT, content=pcm_wav(1), mime_type="audio/wav"
        )

    assert caught.value is failure
    written = recorded.await_args.kwargs
    assert written["failure_stage"] == "engine"
    assert (written["surface"], written["agent_id"]) == ("chat", _AGENT.id)
    assert (written["provider"], written["model"]) == ("openai", "gpt-4o-transcribe")
    assert (written["units"], written["unit"]) == (0, "")


@pytest.mark.parametrize(
    ("provider_seconds", "reported", "audio_ms"),
    [
        (4.5, 9.0, 4500),
        (None, 9.25, 9250),
        (None, 10_000.0, 300_000),
        (None, None, None),
    ],
    ids=["provider-wins", "browser-fallback", "clamped-to-the-cap", "nobody-says"],
)
async def test_a_compressed_length_is_the_providers_else_the_browsers_clamped(
    recorded: Any,
    compressed: AsyncMock,
    provider_seconds: float | None,
    reported: float | None,
    audio_ms: int | None,
) -> None:
    """Where a compressed recording's length cannot be read, the browser's
    figure is client-reported: second to the provider's, and never longer than
    the organization's longest dictation."""
    compressed.return_value = True
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("ok", provider_seconds)),
        ),
    ):
        await MLService(_db()).dictate(
            _ctx(), agent=_AGENT, content=b"a", mime_type="audio/webm", reported_seconds=reported
        )

    assert recorded.await_args.kwargs["audio_ms"] == audio_ms


async def test_a_refused_dictation_keeps_the_length_the_browser_reported(
    recorded: Any, compressed: AsyncMock
) -> None:
    compressed.return_value = True
    failure = ExternalServiceError(message="m", details={"reason": "timeout", "stage": "engine"})
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(side_effect=failure),
        ),
        pytest.raises(ExternalServiceError),
    ):
        await MLService(_db()).dictate(
            _ctx(), agent=_AGENT, content=b"a", mime_type="audio/webm", reported_seconds=12.0
        )

    assert recorded.await_args.kwargs["audio_ms"] == 12_000


async def test_a_transcription_refusal_that_cannot_be_committed_still_reaches_the_caller(
    recorded: Any, api_org: AsyncMock
) -> None:
    """The bookkeeping fails on its own: rolled back and logged, the refusal unchanged."""
    api_org.return_value = None
    db = _db()
    db.commit = AsyncMock(side_effect=RuntimeError("no database"))
    with (
        patch("app.services.ml.facade.speech_to_text.default_choice", return_value=None),
        pytest.raises(BadRequestError),
    ):
        await MLService(db).transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider=None,
            model=None,
        )

    db.rollback.assert_awaited_once()
    assert recorded.await_args.kwargs["provider"] is None


# -- reading the log back ------------------------------------------------------


@pytest.mark.security
async def test_a_call_record_from_another_tenant_reads_as_absent() -> None:
    service = MLService(_db())
    with (
        patch(f"{_REPO}.get", new=AsyncMock(return_value=None)),
        pytest.raises(NotFoundError),
    ):
        await service.call_record(_ctx(), uuid.uuid4())


async def test_a_call_record_is_looked_up_inside_the_callers_organization() -> None:
    row = SimpleNamespace(id=uuid.uuid4())
    service = MLService(_db())
    with patch(f"{_REPO}.get", new=AsyncMock(return_value=row)) as get:
        found = await service.call_record(_ctx(), row.id)

    assert found is row
    assert get.await_args.kwargs["organization_id"] == _ORG


async def test_the_listing_pages_and_counts_inside_the_organization() -> None:
    rows = [SimpleNamespace(id=uuid.uuid4())]
    agent_id, bot_id = uuid.uuid4(), uuid.uuid4()
    since = datetime(2026, 10, 1, tzinfo=UTC)
    service = MLService(_db())
    with (
        patch(f"{_REPO}.list_for", new=AsyncMock(return_value=rows)) as listed,
        patch(f"{_REPO}.count_for", new=AsyncMock(return_value=7)) as counted,
    ):
        found, total = await service.call_records(
            _ctx(),
            service="speech_to_text",
            agent_id=agent_id,
            channel_bot_id=bot_id,
            surface="channel",
            since=since,
            skip=10,
            limit=5,
        )

    assert (found, total) == (rows, 7)
    filters = CallFilters(
        service="speech_to_text",
        agent_id=agent_id,
        channel_bot_id=bot_id,
        surface="channel",
        since=since,
        until=None,
    )
    assert listed.await_args.kwargs == {
        "organization_id": _ORG,
        "filters": filters,
        "skip": 10,
        "limit": 5,
    }
    assert counted.await_args.kwargs == {"organization_id": _ORG, "filters": filters}


@pytest.mark.parametrize(
    "narrowing",
    [
        {"agent_id": uuid.uuid4()},
        {"channel_bot_id": uuid.uuid4()},
        {"surface": "channel"},
    ],
    ids=["agent", "bot", "surface"],
)
async def test_filtering_by_attribution_without_runs_view_is_refused(
    narrowing: dict[str, Any],
) -> None:
    """A Member holds `ml:invoke` and not `runs:view`: the per-agent count the
    summary refuses them is not theirs one filter at a time either."""
    member = AuthContext(
        user_id=_CALLER, organization_id=_ORG, role=OrgRoleName.MEMBER.value, is_app_admin=False
    )
    with (
        patch(f"{_REPO}.list_for", new=AsyncMock()) as listed,
        pytest.raises(AuthorizationError) as refused,
    ):
        await MLService(_db()).call_records(member, service=None, skip=0, limit=10, **narrowing)

    assert refused.value.details == {"required": ["runs:view"]}
    listed.assert_not_awaited()
    assert MLService.sees_attribution(member) is False
    assert MLService.sees_attribution(_ctx()) is True


async def test_the_summary_reads_the_callers_organization_over_the_window() -> None:
    summary = SimpleNamespace(seconds=0)
    with patch(f"{_REPO}.summarise", new=AsyncMock(return_value=summary)) as summarise:
        found = await MLService(_db()).usage_summary(_ctx(), service="speech_to_text", days=7)

    assert found is summary
    sent = summarise.await_args.kwargs
    assert (sent["organization_id"], sent["service"]) == (_ORG, "speech_to_text")
    assert abs(datetime.now(UTC) - timedelta(days=7) - sent["since"]) < timedelta(minutes=1)


def test_the_catalog_is_reachable_without_a_database() -> None:
    assert MLService(_db()).catalog()
