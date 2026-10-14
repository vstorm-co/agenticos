"""Turning a voice note into text, and every way that can fail with a reason.

Almost all of this is about refusals. Every failure raises a domain exception
whose `details.reason` names it - `not_configured`, `too_large`, `empty`,
`provider_error`, `timeout` - so a channel bot can say it could not listen to
*this* message and the composer can say why.

The other half is what must never reach a caller: a provider client puts the
failing request URL in its exception message, and a URL carries a key in its
query string.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.core.exceptions import (
    AppException,
    BadRequestError,
    ConfigurationError,
    ExternalServiceError,
)
from app.services import speech_to_text
from app.services.organization_secret import OrganizationSecretService
from app.services.transcription import (
    MAX_BYTES,
    RECORDING_EXTENSIONS,
    RECORDING_TYPE_ALIASES,
    Recording,
    TranscriptionService,
    audio_seconds_of,
    recording_type,
)

pytestmark = pytest.mark.anyio

ORG = uuid4()


KEY = uuid4()


@pytest.fixture(autouse=True)
def vault_key(monkeypatch) -> AsyncMock:
    """The named key opens to `sk-test-key`, unless a test says it is not usable."""
    found = AsyncMock(return_value="sk-test-key")
    monkeypatch.setattr(OrganizationSecretService, "transcription_key", found)
    return found


def _recording(content: bytes = b"ogg-bytes") -> Recording:
    return Recording(content=content, filename="voice.ogg", mime_type="audio/ogg")


def _offered() -> tuple[str, str]:
    provider = speech_to_text.providers()[0]
    return provider.provider, provider.models[0].id


def _responds(payload: object, *, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.json = MagicMock(return_value=payload)
    response.raise_for_status = MagicMock(
        side_effect=None
        if status < 400
        else httpx.HTTPStatusError("boom", request=MagicMock(), response=MagicMock())
    )
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestATranscriptionThatWorks:
    async def test_the_words_come_back(self, monkeypatch):
        provider, model = _offered()
        client = _responds({"text": "  co tu widzisz  "})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            found = await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider=provider,
                model=model,
            )

        assert found.text == "co tu widzisz"

    async def test_it_posts_the_recording_as_multipart_to_the_right_endpoint(self, monkeypatch):
        provider, model = _offered()
        client = _responds({"text": "hello"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider=provider,
                model=model,
            )

        call = client.post.await_args
        assert call.args[0].endswith("/audio/transcriptions")
        assert call.kwargs["data"]["model"] == model
        assert call.kwargs["files"]["file"][0] == "voice.ogg"
        assert call.kwargs["headers"]["Authorization"] == "Bearer sk-test-key"


class TestEveryFailureIsNamed:
    async def test_a_model_the_catalog_does_not_list(self, monkeypatch):
        provider, _ = _offered()

        with pytest.raises(ConfigurationError) as raised:
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider=provider,
                model="whisper-imaginary",
            )

        assert raised.value.details["reason"] == "not_configured"

    async def test_a_provider_that_cannot_transcribe(self):
        with pytest.raises(ConfigurationError) as raised:
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider="anthropic",
                model="whisper-1",
            )

        assert raised.value.details["reason"] == "not_configured"

    async def test_a_recording_over_the_endpoints_limit_is_not_uploaded(self, monkeypatch):
        """Refused before the POST: a 25 MB upload that comes back 413 has spent
        the time twice, and somebody is waiting."""
        provider, model = _offered()
        client = _responds({"text": "never asked"})

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(BadRequestError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(b"x" * (MAX_BYTES + 1)),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider=provider,
                model=model,
            )

        assert raised.value.details["reason"] == "too_large"
        client.post.assert_not_awaited()

    async def test_a_refusal_from_the_endpoint(self, monkeypatch):
        provider, model = _offered()
        client = _responds({}, status=429)

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(ExternalServiceError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider=provider,
                model=model,
            )

        assert raised.value.details["reason"] == "provider_error"

    async def test_a_timeout(self, monkeypatch):
        provider, model = _offered()
        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.ReadTimeout("too slow"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(ExternalServiceError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider=provider,
                model=model,
            )

        assert raised.value.details["reason"] == "timeout"

    @pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": "   "}, [], "text"])
    async def test_an_answer_with_no_words_in_it(self, monkeypatch, payload: object):
        """Silence transcribed as an empty string must not become an empty user
        message: the caller has to be able to tell that apart from words."""
        provider, model = _offered()
        client = _responds(payload)

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(BadRequestError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider=provider,
                model=model,
            )

        assert raised.value.details["reason"] == "empty"


class TestTheNamedKey:
    """The key is the one named next to the pair - opened, never looked up (#1797)."""

    async def test_the_named_key_is_sent_to_the_catalogs_address(self, vault_key: AsyncMock):
        provider, model = _offered()
        client = _responds({"text": "hi"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                provider=provider,
                model=model,
                secret_id=KEY,
                shared_key=True,
            )

        sent = client.post.await_args
        assert sent.kwargs["headers"] == {"Authorization": "Bearer sk-test-key"}
        entry = speech_to_text.by_provider(provider)
        assert entry is not None
        assert sent.args[0] == f"{entry.base_url.rstrip('/')}/audio/transcriptions"
        assert vault_key.await_args.args == (ORG, KEY)
        assert vault_key.await_args.kwargs == {"provider": provider, "shared": True}

    async def test_an_agents_key_is_opened_as_lent_not_shared(self, vault_key: AsyncMock):
        """An agent's key need not be organization-visible: its publisher lent it."""
        provider, model = _offered()

        with patch(
            "app.services.transcription.httpx.AsyncClient", return_value=_responds({"text": "a"})
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                provider=provider,
                model=model,
                secret_id=KEY,
                shared_key=False,
            )

        assert vault_key.await_args.kwargs["shared"] is False

    async def test_no_key_named_is_refused_without_a_lookup_or_a_request(
        self, monkeypatch, vault_key: AsyncMock
    ):
        """And never the deployment's own environment key in its place."""
        provider, model = _offered()
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-environment")
        client = _responds({"text": "never asked"})

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(ConfigurationError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                provider=provider,
                model=model,
                secret_id=None,
                shared_key=True,
            )

        assert raised.value.details["reason"] == "not_configured"
        vault_key.assert_not_awaited()
        client.post.assert_not_awaited()

    async def test_a_named_key_that_is_not_usable_is_refused(self, vault_key: AsyncMock):
        """Deleted, for another provider, or made private since: the vault says
        none, and nothing else is tried in its place."""
        provider, model = _offered()
        vault_key.return_value = None
        client = _responds({"text": "never asked"})

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(ConfigurationError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                provider=provider,
                model=model,
                secret_id=KEY,
                shared_key=True,
            )

        assert raised.value.details["reason"] == "not_configured"
        client.post.assert_not_awaited()


class TestWhetherAKeyIsUsable:
    """Existence only: a readiness check asks without a plaintext being opened."""

    async def test_no_key_named_is_not_usable_and_nothing_is_read(self, monkeypatch):
        usable = AsyncMock()
        monkeypatch.setattr(OrganizationSecretService, "usable_transcription_key", usable)

        found = await TranscriptionService(MagicMock()).has_key(
            ORG, provider="openai", secret_id=None, shared_key=True
        )

        assert found is False
        usable.assert_not_awaited()

    @pytest.mark.parametrize(("row", "expected"), [(object(), True), (None, False)])
    async def test_the_vault_decides_without_unsealing(
        self, monkeypatch, vault_key: AsyncMock, row: object, expected: bool
    ):
        usable = AsyncMock(return_value=row)
        monkeypatch.setattr(OrganizationSecretService, "usable_transcription_key", usable)

        found = await TranscriptionService(MagicMock()).has_key(
            ORG, provider="groq", secret_id=KEY, shared_key=False
        )

        assert found is expected
        assert usable.await_args.args == (ORG, KEY)
        assert usable.await_args.kwargs == {"provider": "groq", "shared": False}
        vault_key.assert_not_awaited()


class TestTheLanguage:
    async def test_the_language_is_sent_when_one_is_set(self, monkeypatch):
        provider, model = _offered()
        client = _responds({"text": "cześć"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider=provider,
                model=model,
                language="pl",
            )

        assert client.post.await_args.kwargs["data"] == {"model": model, "language": "pl"}

    async def test_no_language_sends_only_the_model(self, monkeypatch):
        """Left out rather than sent empty, so the engine detects the language."""
        provider, model = _offered()
        client = _responds({"text": "hi"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(),
                organization_id=ORG,
                secret_id=KEY,
                shared_key=True,
                provider=provider,
                model=model,
            )

        assert client.post.await_args.kwargs["data"] == {"model": model}


@pytest.mark.parametrize(
    ("payload", "seconds"),
    [
        ({"text": "a", "usage": {"type": "duration", "seconds": 3}}, 3.0),
        ({"text": "a", "usage": {"type": "tokens", "input_tokens": 40}}, None),
        ({"text": "a", "usage": {"prompt_audio_seconds": 7, "prompt_tokens": 9}}, 7.0),
        ({"text": "a", "duration": 2.48, "x_groq": {"id": "req_1"}}, 2.48),
        ({"text": "a"}, None),
        ({"text": "a", "duration": "12"}, None),
        ({"text": "a", "duration": True}, None),
        ({"text": "a", "duration": 0}, None),
        ({"text": "a", "usage": "duration"}, None),
    ],
    ids=[
        "openai-whisper",
        "openai-gpt-4o-tokens",
        "mistral",
        "groq-verbose",
        "nothing",
        "a-string",
        "a-boolean",
        "zero",
        "usage-not-an-object",
    ],
)
def test_a_providers_length_is_read_in_its_own_shape(
    payload: dict[str, object], seconds: float | None
) -> None:
    """`gpt-4o-transcribe` bills tokens, and a token count is not a length."""
    assert audio_seconds_of(payload) == seconds


async def test_the_length_comes_back_with_the_words(monkeypatch) -> None:
    provider, model = _offered()
    client = _responds({"text": "hi", "usage": {"type": "duration", "seconds": 4}})

    with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
        found = await TranscriptionService(MagicMock()).transcribe(
            _recording(),
            organization_id=ORG,
            secret_id=KEY,
            shared_key=True,
            provider=provider,
            model=model,
        )

    assert (found.text, found.audio_seconds) == ("hi", 4.0)


async def test_groq_is_asked_for_the_verbose_answer_that_carries_a_length(monkeypatch) -> None:
    """Groq states `duration` only in `verbose_json`; its catalog entry says so."""
    entry = speech_to_text.by_provider("groq")
    assert entry is not None
    assert entry.response_format == "verbose_json"
    client = _responds({"text": "hi", "duration": 1.5})

    with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
        found = await TranscriptionService(MagicMock()).transcribe(
            _recording(),
            organization_id=ORG,
            secret_id=KEY,
            shared_key=True,
            provider="groq",
            model=entry.models[0].id,
        )

    assert client.post.await_args.kwargs["data"]["response_format"] == "verbose_json"
    assert found.audio_seconds == 1.5


@pytest.mark.parametrize("provider", ["openai", "mistral"])
def test_providers_whose_plain_answer_has_a_length_are_sent_no_format(provider: str) -> None:
    """OpenAI's `gpt-4o-*` refuse `verbose_json`; plain JSON is what they all accept."""
    entry = speech_to_text.by_provider(provider)
    assert entry is not None
    assert entry.response_format is None


@pytest.mark.parametrize(
    ("setup", "error", "reason", "stage"),
    [
        ("no_key", ConfigurationError, "not_configured", None),
        ("not_offered", ConfigurationError, "not_configured", None),
        ("too_large", BadRequestError, "too_large", None),
        ("http_error", ExternalServiceError, "provider_error", "engine"),
        ("timeout", ExternalServiceError, "timeout", "engine"),
        ("empty", BadRequestError, "empty", "engine"),
    ],
)
async def test_each_failure_raises_with_a_reason_and_no_provider_text(
    vault_key: AsyncMock, setup: str, error: type[AppException], reason: str, stage: str | None
) -> None:
    """The reason is what a caller acts on; the provider's text, which can carry
    the request URL and its key, is what it must never see.

    The engine's own failures say `stage="engine"`, so the ML usage log records
    them against the engine rather than against the caller's input."""
    provider, model = _offered()
    recording = _recording()
    client = _responds({"text": "hi"})
    if setup == "no_key":
        vault_key.return_value = None
    if setup == "not_offered":
        model = "no-such-model"
    if setup == "too_large":
        recording = _recording(b"x" * (MAX_BYTES + 1))
    if setup == "http_error":
        client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "401 for https://api.example/?key=sk-leak",
                request=MagicMock(),
                response=MagicMock(),
            )
        )
    if setup == "timeout":
        client.post = AsyncMock(side_effect=httpx.ReadTimeout("slow at ?key=sk-leak"))
    if setup == "empty":
        client = _responds({"text": "   "})

    with (
        patch("app.services.transcription.httpx.AsyncClient", return_value=client),
        pytest.raises(error) as raised,
    ):
        await TranscriptionService(MagicMock()).transcribe(
            recording,
            organization_id=ORG,
            secret_id=KEY,
            shared_key=True,
            provider=provider,
            model=model,
        )

    assert raised.value.details is not None
    assert raised.value.details["reason"] == reason
    assert raised.value.details.get("stage") == stage
    assert raised.value.details["provider"] == provider
    assert "sk-leak" not in raised.value.message
    assert "sk-leak" not in str(raised.value.details)


class TestWhatARecordingIsCalled:
    """One table for dictation and channel voice notes, so the two agree."""

    @pytest.mark.parametrize(
        ("claimed", "base"),
        [
            ("audio/webm;codecs=opus", "audio/webm"),
            ("Audio/X-WAV", "audio/wav"),
            ("audio/wave", "audio/wav"),
            ("audio/x-m4a", "audio/mp4"),
            ("audio/m4a", "audio/mp4"),
            ("audio/opus", "audio/ogg"),
            ("audio/x-ogg", "audio/ogg"),
            ("audio/mp3", "audio/mpeg"),
            ("audio/flac", "audio/flac"),
        ],
    )
    def test_a_type_is_read_without_parameters_and_by_its_usual_name(self, claimed: str, base: str):
        assert recording_type(claimed) == base

    def test_every_alias_names_a_type_with_an_extension(self):
        """An alias to a type the table has no extension for would rename
        nothing, and the provider would be sent the platform's name again."""
        assert set(RECORDING_TYPE_ALIASES.values()) <= set(RECORDING_EXTENSIONS)
