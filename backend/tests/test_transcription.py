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

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.core.exceptions import (
    AppException,
    BadRequestError,
    ConfigurationError,
    ExternalServiceError,
)
from app.core.secret_kinds import ApiKeySecret, NoSecret
from app.repositories import credential as credential_repo
from app.services import speech_to_text
from app.services.model_profile import ModelProfileService
from app.services.transcription import MAX_BYTES, Recording, TranscriptionService

pytestmark = pytest.mark.anyio

ORG = uuid4()


def _recording(content: bytes = b"ogg-bytes") -> Recording:
    return Recording(content=content, filename="voice.ogg", mime_type="audio/ogg")


def _offered() -> tuple[str, str]:
    provider = speech_to_text.providers()[0]
    return provider.provider, provider.models[0].id


def _profile(provider: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), provider=provider, label="the key", model="x")


def _with_key(monkeypatch, provider: str, *, base_url: str | None = None) -> None:
    monkeypatch.setattr(
        credential_repo, "list_profiles", AsyncMock(return_value=[_profile(provider)])
    )
    monkeypatch.setattr(
        ModelProfileService,
        "resolve_credential",
        AsyncMock(
            return_value=SimpleNamespace(
                provider=provider,
                secret=ApiKeySecret(api_key=SecretStr("sk-test-key")),
                base_url=base_url,
            )
        ),
    )


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
        _with_key(monkeypatch, provider)
        client = _responds({"text": "  co tu widzisz  "})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            found = await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert found == "co tu widzisz"

    async def test_it_posts_the_recording_as_multipart_to_the_right_endpoint(self, monkeypatch):
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = _responds({"text": "hello"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        call = client.post.await_args
        assert call.args[0].endswith("/audio/transcriptions")
        assert call.kwargs["data"]["model"] == model
        assert call.kwargs["files"]["file"][0] == "voice.ogg"
        assert call.kwargs["headers"]["Authorization"] == "Bearer sk-test-key"

    async def test_the_organizations_own_endpoint_wins_over_the_catalogs(self, monkeypatch):
        """Which is how a proxy or a self-hosted server is reached: the profile
        carries the address, and the catalog's is the public default."""
        provider, model = _offered()
        _with_key(monkeypatch, provider, base_url="https://llm.acme.internal/v1")
        client = _responds({"text": "hello"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert client.post.await_args.args[0].startswith("https://llm.acme.internal/v1")


class TestEveryFailureIsNamed:
    async def test_a_model_the_catalog_does_not_list(self, monkeypatch):
        provider, _ = _offered()
        _with_key(monkeypatch, provider)

        with pytest.raises(ConfigurationError) as raised:
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model="whisper-imaginary"
            )

        assert raised.value.details["reason"] == "not_configured"

    async def test_a_provider_that_cannot_transcribe(self):
        with pytest.raises(ConfigurationError) as raised:
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider="anthropic", model="whisper-1"
            )

        assert raised.value.details["reason"] == "not_configured"

    async def test_a_recording_over_the_endpoints_limit_is_not_uploaded(self, monkeypatch):
        """Refused before the POST: a 25 MB upload that comes back 413 has spent
        the time twice, and somebody is waiting."""
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = _responds({"text": "never asked"})

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(BadRequestError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(b"x" * (MAX_BYTES + 1)),
                organization_id=ORG,
                provider=provider,
                model=model,
            )

        assert raised.value.details["reason"] == "too_large"
        client.post.assert_not_awaited()

    async def test_no_credential_for_that_provider(self, monkeypatch):
        provider, model = _offered()
        monkeypatch.setattr(credential_repo, "list_profiles", AsyncMock(return_value=[]))

        with pytest.raises(ConfigurationError) as raised:
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert raised.value.details["reason"] == "not_configured"

    async def test_a_profile_whose_secret_is_gone_is_skipped_for_the_next(self, monkeypatch):
        """Refusing on the first would make transcription depend on row order."""
        provider, model = _offered()
        monkeypatch.setattr(
            credential_repo,
            "list_profiles",
            AsyncMock(return_value=[_profile(provider), _profile(provider)]),
        )
        monkeypatch.setattr(
            ModelProfileService,
            "resolve_credential",
            AsyncMock(
                side_effect=[
                    RuntimeError("that key was deleted"),
                    SimpleNamespace(
                        provider=provider,
                        secret=ApiKeySecret(api_key=SecretStr("sk-second")),
                        base_url=None,
                    ),
                ]
            ),
        )
        client = _responds({"text": "hello"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            found = await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert found == "hello"
        assert client.post.await_args.kwargs["headers"]["Authorization"] == "Bearer sk-second"

    @pytest.mark.parametrize("secret", [SimpleNamespace(), NoSecret()])
    async def test_a_credential_that_is_not_a_key_is_not_used_as_one(
        self, monkeypatch, secret: object
    ):
        """Neither a credential of another kind nor a keyless profile with no
        address of its own has anything to send: the catalog's public endpoint
        with no key is a request bound to be refused."""
        provider, model = _offered()
        monkeypatch.setattr(
            credential_repo, "list_profiles", AsyncMock(return_value=[_profile(provider)])
        )
        monkeypatch.setattr(
            ModelProfileService,
            "resolve_credential",
            AsyncMock(
                return_value=SimpleNamespace(provider=provider, secret=secret, base_url=None)
            ),
        )

        with pytest.raises(ConfigurationError) as raised:
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert raised.value.details["reason"] == "not_configured"

    async def test_a_refusal_from_the_endpoint(self, monkeypatch):
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = _responds({}, status=429)

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(ExternalServiceError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert raised.value.details["reason"] == "provider_error"

    async def test_a_timeout(self, monkeypatch):
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.ReadTimeout("too slow"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(ExternalServiceError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert raised.value.details["reason"] == "timeout"

    @pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": "   "}, [], "text"])
    async def test_an_answer_with_no_words_in_it(self, monkeypatch, payload: object):
        """Silence transcribed as an empty string must not become an empty user
        message: the caller has to be able to tell that apart from words."""
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = _responds(payload)

        with (
            patch("app.services.transcription.httpx.AsyncClient", return_value=client),
            pytest.raises(BadRequestError) as raised,
        ):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert raised.value.details["reason"] == "empty"


def _profiles(monkeypatch, *pairs: tuple[str, object]) -> None:
    """Profiles in label order, each resolving to the secret given beside it.

    A keyless secret resolves with an address of its own, as a self-hosted
    profile must; a keyed one with none, so it falls back to the catalog's.
    """
    rows = [
        SimpleNamespace(id=uuid4(), provider=provider, label=f"{index}", model="x")
        for index, (provider, _) in enumerate(pairs)
    ]
    secrets = {row.id: secret for row, (_, secret) in zip(rows, pairs, strict=True)}
    monkeypatch.setattr(credential_repo, "list_profiles", AsyncMock(return_value=rows))

    async def resolve(_self: object, _org: object, profile: SimpleNamespace) -> SimpleNamespace:
        secret = secrets[profile.id]
        return SimpleNamespace(
            provider=profile.provider,
            secret=secret,
            base_url="http://whisper.local:8000/v1" if isinstance(secret, NoSecret) else None,
        )

    monkeypatch.setattr(ModelProfileService, "resolve_credential", resolve)


class TestWhichCredentialTranscribes:
    async def test_a_keyed_profile_wins_over_a_keyless_one_that_sorts_first(self, monkeypatch):
        """Existing bots keep their vendor: a self-hosted chat proxy must not take
        their voice notes just because its label sorts earlier."""
        provider, model = _offered()
        _profiles(
            monkeypatch,
            (provider, NoSecret()),
            (provider, ApiKeySecret(api_key=SecretStr("sk-real-key-1234"))),
        )
        client = _responds({"text": "hi"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        sent = client.post.await_args
        assert sent.kwargs["headers"] == {"Authorization": "Bearer sk-real-key-1234"}
        assert not sent.args[0].startswith("http://whisper.local")

    async def test_only_a_keyless_profile_is_used_with_no_authorization_header(self, monkeypatch):
        """And never with the deployment's own `OPENAI_API_KEY` slipped in: a
        self-hosted server is reached unauthenticated, as its profile says."""
        provider, model = _offered()
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-environment")
        _profiles(monkeypatch, (provider, NoSecret()))
        client = _responds({"text": "hi"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            text = await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert text == "hi"
        sent = client.post.await_args
        assert sent.args[0] == "http://whisper.local:8000/v1/audio/transcriptions"
        assert "Authorization" not in sent.kwargs["headers"]
        assert "sk-from-the-environment" not in str(sent)


class TestTheLanguage:
    async def test_the_language_is_sent_when_one_is_set(self, monkeypatch):
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = _responds({"text": "cześć"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model, language="pl"
            )

        assert client.post.await_args.kwargs["data"] == {"model": model, "language": "pl"}

    async def test_no_language_sends_only_the_model(self, monkeypatch):
        """Left out rather than sent empty, so the engine detects the language."""
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = _responds({"text": "hi"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert client.post.await_args.kwargs["data"] == {"model": model}


@pytest.mark.parametrize(
    ("setup", "error", "reason", "stage"),
    [
        ("no_profile", ConfigurationError, "not_configured", None),
        ("not_offered", ConfigurationError, "not_configured", None),
        ("too_large", BadRequestError, "too_large", None),
        ("http_error", ExternalServiceError, "provider_error", "engine"),
        ("timeout", ExternalServiceError, "timeout", "engine"),
        ("empty", BadRequestError, "empty", "engine"),
    ],
)
async def test_each_failure_raises_with_a_reason_and_no_provider_text(
    monkeypatch, setup: str, error: type[AppException], reason: str, stage: str | None
) -> None:
    """The reason is what a caller acts on; the provider's text, which can carry
    the request URL and its key, is what it must never see.

    The engine's own failures say `stage="engine"`, so the ML usage log records
    them against the engine rather than against the caller's input."""
    provider, model = _offered()
    recording = _recording()
    client = _responds({"text": "hi"})
    if setup == "no_profile":
        monkeypatch.setattr(credential_repo, "list_profiles", AsyncMock(return_value=[]))
    else:
        _with_key(monkeypatch, provider)
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
            recording, organization_id=ORG, provider=provider, model=model
        )

    assert raised.value.details is not None
    assert raised.value.details["reason"] == reason
    assert raised.value.details.get("stage") == stage
    assert raised.value.details["provider"] == provider
    assert "sk-leak" not in raised.value.message
    assert "sk-leak" not in str(raised.value.details)
