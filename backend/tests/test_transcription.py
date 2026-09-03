"""Turning a voice note into text, and every way that can fail harmlessly.

Almost all of this is about `None`. Transcription sits in front of an answer
somebody is waiting for in a chat window, so every failure has to end with the
bot saying it could not listen to *this* message rather than going quiet - a
provider being rate-limited must not look like a broken bot.

The other half is what must never reach the chat: a provider client puts the
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

from app.core.secret_kinds import ApiKeySecret
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
                secret=ApiKeySecret(api_key=SecretStr("sk-test")),
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
        assert call.kwargs["headers"]["Authorization"] == "Bearer sk-test"

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


class TestEveryFailureIsHarmless:
    async def test_a_model_the_catalog_does_not_list(self, monkeypatch):
        provider, _ = _offered()
        _with_key(monkeypatch, provider)

        found = await TranscriptionService(MagicMock()).transcribe(
            _recording(), organization_id=ORG, provider=provider, model="whisper-imaginary"
        )

        assert found is None

    async def test_a_provider_that_cannot_transcribe(self):
        found = await TranscriptionService(MagicMock()).transcribe(
            _recording(), organization_id=ORG, provider="anthropic", model="whisper-1"
        )

        assert found is None

    async def test_a_recording_over_the_endpoints_limit_is_not_uploaded(self, monkeypatch):
        """Refused before the POST: a 25 MB upload that comes back 413 has spent
        the time twice, and somebody is waiting."""
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = _responds({"text": "never asked"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            found = await TranscriptionService(MagicMock()).transcribe(
                _recording(b"x" * (MAX_BYTES + 1)),
                organization_id=ORG,
                provider=provider,
                model=model,
            )

        assert found is None
        client.post.assert_not_awaited()

    async def test_no_credential_for_that_provider(self, monkeypatch):
        provider, model = _offered()
        monkeypatch.setattr(credential_repo, "list_profiles", AsyncMock(return_value=[]))

        found = await TranscriptionService(MagicMock()).transcribe(
            _recording(), organization_id=ORG, provider=provider, model=model
        )

        assert found is None

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

    async def test_a_credential_that_is_not_a_key_is_not_used_as_one(self, monkeypatch):
        """A keyless self-hosted profile resolves to `NoSecret`, which has no
        bearer token to send."""
        provider, model = _offered()
        monkeypatch.setattr(
            credential_repo, "list_profiles", AsyncMock(return_value=[_profile(provider)])
        )
        monkeypatch.setattr(
            ModelProfileService,
            "resolve_credential",
            AsyncMock(
                return_value=SimpleNamespace(
                    provider=provider, secret=SimpleNamespace(), base_url=None
                )
            ),
        )

        found = await TranscriptionService(MagicMock()).transcribe(
            _recording(), organization_id=ORG, provider=provider, model=model
        )

        assert found is None

    async def test_a_refusal_from_the_endpoint(self, monkeypatch):
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = _responds({}, status=429)

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            found = await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert found is None

    async def test_a_timeout(self, monkeypatch):
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.ReadTimeout("too slow"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            found = await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert found is None

    @pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": "   "}, [], "text"])
    async def test_an_answer_with_no_words_in_it(self, monkeypatch, payload: object):
        """Silence transcribed as an empty string must not become an empty user
        message: the caller has to be able to tell that apart from words."""
        provider, model = _offered()
        _with_key(monkeypatch, provider)
        client = _responds(payload)

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            found = await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert found is None
