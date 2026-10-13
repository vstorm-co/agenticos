"""The ML facade: tenant scoping, the usage record, and what each refusal says.

The engines are covered by `test_ml_parsing.py` and `test_ml_pii.py`. What is
left is everything this layer adds - that a successful call is recorded in the
caller's own transaction and a refused one committed before that transaction
rolls back, that the record carries the organization the caller is acting in,
and that the two rows the surface reaches by id (a registered OCR server, a call
record) are scoped so that another tenant's is simply absent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException, BadRequestError, ExternalServiceError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.repositories.ml_service_call import CallFilters
from app.services.ml import parsing
from app.services.ml.facade import MLService
from app.services.transcription import TranscriptionResult

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CALLER = uuid.uuid4()
_REPO = "app.services.ml.facade.ml_service_call_repo"


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
    service = MLService(_db())
    with (
        patch(
            "app.services.ml.facade.speech_to_text.default_choice",
            return_value=("openai", "whisper-1"),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("hello there", 2.2)),
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
        patch(
            "app.services.ml.facade.TranscriptionService.transcribe",
            new=AsyncMock(return_value=_heard("hello")),
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
        patch(f"{_REPO}.record", new=AsyncMock()),
    ):
        transcript = await service.transcribe(
            _ctx(),
            content=b"audio",
            filename="voice.ogg",
            mime_type="audio/ogg",
            provider="groq",
            model=None,
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


async def test_a_deployment_that_offers_no_transcription_says_so() -> None:
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


# -- dictation into the composer (#1797) ---------------------------------------


_AGENT = SimpleNamespace(
    id=uuid.uuid4(), organization_id=_ORG, name="Support", status="draft", current_version_id=None
)
"""An agent with nothing published, so the organization's settings answer alone."""

_SETTINGS = "app.services.speech_to_text_settings"


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
        "chat_dictation": "server",
        "speech_to_text_provider": "openai",
        "speech_to_text_model": "gpt-4o-transcribe",
        "speech_to_text_language": "pl",
        "dictation_max_seconds": 300,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


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
            _ctx(), agent=_AGENT, content=b"audio", mime_type="audio/webm;codecs=opus"
        )

    assert text == "dzień dobry"
    assert get.await_args.args[1] == _ORG
    sent = transcribe.await_args
    assert sent.args[0].filename == "recording.webm"
    assert sent.args[0].mime_type == "audio/webm"
    assert sent.kwargs["organization_id"] == _ORG
    assert (sent.kwargs["provider"], sent.kwargs["model"]) == ("openai", "gpt-4o-transcribe")
    assert sent.kwargs["language"] == "pl"
    written = recorded.await_args.kwargs
    assert written["service"] == "speech_to_text"
    assert (written["surface"], written["agent_id"]) == ("chat", _AGENT.id)
    assert (written["provider"], written["model"]) == ("openai", "gpt-4o-transcribe")
    assert written["requested_by_user_id"] == _CALLER
    assert (written["units"], written["unit"], written["audio_ms"]) == (0, "seconds", None)


async def test_a_dictation_uses_the_agents_published_override(recorded: Any) -> None:
    """A Polish agent in an organization set up for another engine: the agent's
    pair and language, from the version `/chat` runs."""
    del recorded
    agent, get_version = _published(
        {"provider": "groq", "model": "whisper-large-v3", "language": "de"}
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
        await MLService(_db()).dictate(_ctx(), agent=agent, content=b"a", mime_type="audio/webm")

    sent = transcribe.await_args.kwargs
    assert (sent["provider"], sent["model"], sent["language"]) == ("groq", "whisper-large-v3", "de")
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
        await MLService(_db()).dictate(_ctx(), agent=agent, content=b"a", mime_type="audio/webm")

    assert transcribe.await_args.kwargs["model"] == "whisper-1"
    # The organization's language still applies where the agent pins none.
    assert transcribe.await_args.kwargs["language"] == "pl"


@pytest.mark.parametrize(
    ("org", "agent_override", "credentialed", "ready", "provider"),
    [
        (_speech_org(), None, {"openai"}, True, "openai"),
        (_speech_org(), None, set(), False, "openai"),
        (_speech_org(chat_dictation="browser"), None, {"openai"}, False, "openai"),
        (_speech_org(speech_to_text_model="withdrawn"), None, {"openai"}, False, "openai"),
        (
            _speech_org(speech_to_text_provider=None, speech_to_text_model=None),
            None,
            {"openai"},
            False,
            None,
        ),
        (
            _speech_org(speech_to_text_provider=None, speech_to_text_model=None),
            {"provider": "mistral", "model": "voxtral-mini-latest"},
            {"mistral"},
            True,
            "mistral",
        ),
        (
            _speech_org(),
            {"provider": "mistral", "model": "voxtral-mini-latest"},
            {"openai"},
            False,
            "mistral",
        ),
    ],
    ids=[
        "org-pair",
        "no-credential",
        "browser-engine",
        "withdrawn-model",
        "no-pair",
        "agent-pair-without-org-pair",
        "agent-pair-without-its-credential",
    ],
)
async def test_dictation_readiness_follows_the_resolved_pair(
    org: SimpleNamespace,
    agent_override: dict[str, str] | None,
    credentialed: set[str],
    ready: bool,
    provider: str | None,
) -> None:
    """Ready needs the server engine, a pair that resolves for this agent, the
    catalog still offering it and a credential for its provider. The provider is
    returned regardless, because the composer records in its format."""
    agent, get_version = _published(agent_override)
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id", new=AsyncMock(return_value=org)
        ),
        patch(f"{_SETTINGS}.agent_repo.get_version", new=get_version),
        patch(
            "app.services.ml.facade.TranscriptionService.credentialed_providers",
            new=AsyncMock(return_value=frozenset(credentialed)),
        ),
    ):
        status = await MLService(_db()).dictation_status(_ctx(), agent=agent)

    assert (status.ready, status.provider) == (ready, provider)
    assert status.engine == org.chat_dictation
    assert status.max_seconds == org.dictation_max_seconds


async def test_dictation_readiness_for_an_unpublished_agent_answers_from_the_org() -> None:
    """Never a refusal: the composer asks before the agent has anything published."""
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id",
            new=AsyncMock(return_value=_speech_org()),
        ),
        patch(
            "app.services.ml.facade.TranscriptionService.credentialed_providers",
            new=AsyncMock(return_value=frozenset({"openai"})),
        ),
    ):
        status = await MLService(_db()).dictation_status(_ctx(), agent=_AGENT)

    assert (status.ready, status.provider) == (True, "openai")


async def test_dictation_readiness_with_no_organization_is_not_found() -> None:
    with (
        patch(
            "app.services.ml.facade.organization_repo.get_by_id", new=AsyncMock(return_value=None)
        ),
        pytest.raises(NotFoundError),
    ):
        await MLService(_db()).dictation_status(_ctx(), agent=_AGENT)


async def test_the_credentialed_providers_are_the_callers_organizations() -> None:
    with patch(
        "app.services.ml.facade.TranscriptionService.credentialed_providers",
        new=AsyncMock(return_value=frozenset({"groq"})),
    ) as credentialed:
        found = await MLService(_db()).speech_to_text_credentials(_ctx())

    assert found == frozenset({"groq"})
    assert credentialed.await_args.args[0] == _ORG


@pytest.mark.parametrize(
    ("org", "content", "mime", "reason"),
    [
        (None, b"a", "audio/webm", "not_configured"),
        (_speech_org(chat_dictation="browser"), b"a", "audio/webm", "not_configured"),
        (
            _speech_org(speech_to_text_provider=None, speech_to_text_model=None),
            b"a",
            "audio/webm",
            "not_configured",
        ),
        (_speech_org(), b"", "audio/webm", "empty"),
        (_speech_org(), b"a", "audio/mpeg", "unsupported_type"),
        (_speech_org(dictation_max_seconds=10), b"x" * (10 * 32_768 + 1), "audio/ogg", "too_large"),
    ],
    ids=["no-org", "browser-engine", "no-pair", "empty", "mp3", "over-the-limit"],
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


async def test_a_recording_exactly_at_the_limit_is_transcribed(recorded: Any) -> None:
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
            _ctx(), agent=_AGENT, content=b"x" * (10 * 32_768), mime_type="audio/mp4"
        )

    assert text == "ok"


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
    recorded: Any, mime: str, filename: str, sent_type: str
) -> None:
    """The provider reads the format from the file name. MP4 audio goes as
    `.m4a`, the name every OpenAI-compatible provider lists, and every name for
    WAV arrives as one type."""
    del recorded
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
        await MLService(_db()).dictate(_ctx(), agent=_AGENT, content=b"a", mime_type=mime)

    sent = transcribe.await_args.args[0]
    assert (sent.filename, sent.mime_type) == (filename, sent_type)


async def test_a_wav_recording_of_the_longest_dictation_fits_under_the_cap(
    recorded: Any,
) -> None:
    """The composer records 16 kHz mono 16-bit WAV for Mistral: 32,000 bytes a
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
            _ctx(), agent=_AGENT, content=b"x" * (300 * 32_000 + 44), mime_type="audio/wav"
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
            _ctx(), agent=_AGENT, content=b"a", mime_type="audio/ogg;codecs=opus"
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
async def test_a_dictations_length_is_the_providers_else_the_browsers_clamped(
    recorded: Any, provider_seconds: float | None, reported: float | None, audio_ms: int | None
) -> None:
    """The browser's figure is client-reported: second to the provider's, and
    never longer than the organization's longest dictation."""
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


async def test_a_refused_dictation_keeps_the_length_the_browser_reported(recorded: Any) -> None:
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
    recorded: Any,
) -> None:
    """The bookkeeping fails on its own: rolled back and logged, the refusal unchanged."""
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


async def test_the_summary_reads_the_callers_organization_over_the_window() -> None:
    summary = SimpleNamespace(audio_ms=0)
    with patch(f"{_REPO}.summarise", new=AsyncMock(return_value=summary)) as summarise:
        found = await MLService(_db()).usage_summary(_ctx(), service="speech_to_text", days=7)

    assert found is summary
    sent = summarise.await_args.kwargs
    assert (sent["organization_id"], sent["service"]) == (_ORG, "speech_to_text")
    assert abs(datetime.now(UTC) - timedelta(days=7) - sent["since"]) < timedelta(minutes=1)


def test_the_catalog_is_reachable_without_a_database() -> None:
    assert MLService(_db()).catalog()
