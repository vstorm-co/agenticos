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


@pytest.fixture(autouse=True)
def no_vault_key(monkeypatch) -> AsyncMock:
    """No organization-visible vault key, unless a test stores one."""
    found = AsyncMock(return_value=None)
    monkeypatch.setattr(OrganizationSecretService, "transcription_key", found)
    return found


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

        assert found.text == "co tu widzisz"

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

        assert found.text == "hello"
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

        assert text.text == "hi"
        sent = client.post.await_args
        assert sent.args[0] == "http://whisper.local:8000/v1/audio/transcriptions"
        assert "Authorization" not in sent.kwargs["headers"]
        assert "sk-from-the-environment" not in str(sent)


class TestTheVaultKeyFallback:
    """An organization-visible vault key, when no model profile answers (#1797)."""

    async def test_a_vault_key_transcribes_where_no_profile_exists(
        self, monkeypatch, no_vault_key: AsyncMock
    ):
        """An organization keeping an OpenAI key and running no OpenAI chat model
        should not have to invent one to transcribe. Sent to the catalog's
        address, since a vault key carries none of its own."""
        provider, model = _offered()
        monkeypatch.setattr(credential_repo, "list_profiles", AsyncMock(return_value=[]))
        no_vault_key.return_value = "sk-vault-4242"
        client = _responds({"text": "hi"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        sent = client.post.await_args
        assert sent.kwargs["headers"] == {"Authorization": "Bearer sk-vault-4242"}
        entry = speech_to_text.by_provider(provider)
        assert entry is not None
        assert sent.args[0] == f"{entry.base_url.rstrip('/')}/audio/transcriptions"
        assert no_vault_key.await_args.args == (ORG, provider)

    @pytest.mark.parametrize(
        "secret",
        [ApiKeySecret(api_key=SecretStr("sk-profile-1234")), NoSecret()],
        ids=["keyed", "keyless"],
    )
    async def test_a_profile_wins_over_a_vault_key(
        self, monkeypatch, no_vault_key: AsyncMock, secret: object
    ):
        """The vault is the last place looked, so a bot already transcribing on a
        profile keeps that profile once a key for the provider lands in the vault."""
        provider, model = _offered()
        _profiles(monkeypatch, (provider, secret))
        no_vault_key.return_value = "sk-vault-4242"
        client = _responds({"text": "hi"})

        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            await TranscriptionService(MagicMock()).transcribe(
                _recording(), organization_id=ORG, provider=provider, model=model
            )

        assert "sk-vault-4242" not in str(client.post.await_args)
        no_vault_key.assert_not_awaited()


class TestWhichProvidersAreCredentialed:
    """Existence only: a picker greys out a provider without a key being opened."""

    async def test_each_source_counts_and_nothing_is_unsealed(self, monkeypatch):
        rows = [
            SimpleNamespace(provider="openai", secret_id=uuid4(), base_url=None),
            SimpleNamespace(provider="groq", secret_id=None, base_url=None),
            SimpleNamespace(provider="anthropic", secret_id=uuid4(), base_url=None),
        ]
        monkeypatch.setattr(credential_repo, "list_profiles", AsyncMock(return_value=rows))
        resolve = AsyncMock()
        monkeypatch.setattr(ModelProfileService, "resolve_credential", resolve)
        in_vault = AsyncMock(return_value=frozenset({"mistral"}))
        monkeypatch.setattr(OrganizationSecretService, "transcription_key_providers", in_vault)

        found = await TranscriptionService(MagicMock()).credentialed_providers(ORG)

        # Groq's profile has neither a key nor an address; Anthropic does not
        # transcribe here at all.
        assert found == frozenset({"openai", "mistral"})
        resolve.assert_not_awaited()
        # The vault is only asked about providers no profile answered for.
        assert in_vault.await_args.args == (ORG, ["groq", "mistral"])

    async def test_a_self_hosted_profile_with_an_address_counts(self, monkeypatch):
        rows = [
            SimpleNamespace(provider="openai", secret_id=None, base_url="http://whisper.local/v1")
        ]
        monkeypatch.setattr(credential_repo, "list_profiles", AsyncMock(return_value=rows))
        monkeypatch.setattr(
            OrganizationSecretService,
            "transcription_key_providers",
            AsyncMock(return_value=frozenset()),
        )

        found = await TranscriptionService(MagicMock()).credentialed_providers(ORG)

        assert found == frozenset({"openai"})


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
    _with_key(monkeypatch, provider)
    client = _responds({"text": "hi", "usage": {"type": "duration", "seconds": 4}})

    with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
        found = await TranscriptionService(MagicMock()).transcribe(
            _recording(), organization_id=ORG, provider=provider, model=model
        )

    assert (found.text, found.audio_seconds) == ("hi", 4.0)


async def test_groq_is_asked_for_the_verbose_answer_that_carries_a_length(monkeypatch) -> None:
    """Groq states `duration` only in `verbose_json`; its catalog entry says so."""
    entry = speech_to_text.by_provider("groq")
    assert entry is not None
    assert entry.response_format == "verbose_json"
    _with_key(monkeypatch, "groq")
    client = _responds({"text": "hi", "duration": 1.5})

    with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
        found = await TranscriptionService(MagicMock()).transcribe(
            _recording(), organization_id=ORG, provider="groq", model=entry.models[0].id
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


class TestWhatARecordingIsCalled:
    """One table for dictation and channel voice notes, so the two agree."""

    @pytest.mark.parametrize(
        ("claimed", "base"),
        [
            ("audio/webm;codecs=opus", "audio/webm"),
            ("Audio/X-WAV", "audio/wav"),
            ("audio/wave", "audio/wav"),
            ("audio/x-m4a", "audio/mp4"),
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
