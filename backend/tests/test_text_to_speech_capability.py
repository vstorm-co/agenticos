"""The text-to-speech capability: configure, build, speak, meter, store - and refuse.

The provider is never called: `synthesize` is replaced, so these pin what the tool
does around it - the budget asked with the clip's price before the call, the cost
booked after it (on a partial failure too), the clip kept where an image is kept,
and each failure answered by whoever can fix it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai._run_context import RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend

from app.agents.capabilities import get
from app.agents.capabilities._generated import WORKSPACE_OUTPUT_DIR
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.budget import (
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    guarded_by,
    metered_by,
)
from app.agents.capabilities.text_to_speech import TextToSpeech, TextToSpeechConfig
from app.agents.capabilities.text_to_speech import _toolset as toolset_module
from app.agents.capabilities.text_to_speech._toolset import (
    OfferedVoice,
    build_speech_toolset,
    parse_generated_speech,
)
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.core.secret_kinds import ApiKeySecret
from app.services import text_to_speech_models
from app.services.text_to_speech import SpeechFailure, SpeechProviderError
from app.services.text_to_speech.synthesis import Speech
from tests.workspaces import SandboxUnreachable, document_workspace

pytestmark = pytest.mark.anyio

MP3 = b"ID3-speech"


class _FakeSynthesis:
    """Stands in for `synthesize`, recording what it was asked."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: SpeechProviderError | None = None
        self.spoken_before_error = 0

    async def __call__(self, provider: Any, **kwargs: Any) -> Speech:
        self.calls.append({"provider": provider.provider, **kwargs})
        if self.error is not None:
            if self.spoken_before_error:
                kwargs["on_spoken"](self.spoken_before_error)
            raise self.error
        kwargs["on_spoken"](len(kwargs["text"]))
        return Speech(
            data=MP3,
            audio_format=kwargs["audio_format"],
            characters=len(kwargs["text"]),
            requests=1,
        )


@pytest.fixture
def synthesis(monkeypatch: pytest.MonkeyPatch, tmp_path) -> _FakeSynthesis:
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    fake = _FakeSynthesis()
    monkeypatch.setattr(toolset_module, "synthesize", fake)
    return fake


def _ctx(
    organization_id: Any = None, *, retry: int = 0, workspace: Any = None
) -> RunContext[AgentDeps]:
    ctx = RunContext(
        deps=AgentDeps(organization_id=organization_id),
        model=TestModel(),
        usage=RunUsage(),
        retry=retry,
        max_retries=1,
    )
    if workspace is not None:
        ctx.workspace = workspace
    return ctx


def _toolset(**overrides: Any) -> Any:
    settings_ = {
        "provider": "openai",
        "model": "gpt-4o-mini-tts",
        "voice": "marin",
        "voices": (OfferedVoice("marin"),),
        "audio_format": "mp3",
        "max_characters": 100,
        "api_key": "sk-speech",
    }
    return build_speech_toolset(**{**settings_, **overrides})


async def _speak(
    toolset: Any, ctx: RunContext[AgentDeps], text: str = "Dzień dobry.", **kw: Any
) -> str:
    return await toolset.tools["generate_speech"].function(ctx, text=text, **kw)


def _price(provider: str, model: str) -> Decimal:
    entry = text_to_speech_models.by_provider(provider)
    assert entry is not None
    chosen = entry.model(model)
    assert chosen is not None
    price = text_to_speech_models.price_per_character(chosen, on=datetime.now(UTC).date())
    assert price is not None
    return price


class TestConfiguration:
    def test_turning_it_on_is_enough_to_speak(self):
        config = TextToSpeechConfig()

        assert (config.provider, config.model) == text_to_speech_models.default_choice()
        assert config.resolved_voice() == "marin"
        assert config.resolved_format() == "mp3"

    def test_a_provider_returning_only_wav_resolves_to_wav(self):
        config = TextToSpeechConfig(provider="google", model="gemini-3.8-flash-tts")

        assert config.resolved_format() == "wav"
        assert config.resolved_voice() == "Kore"

    def test_a_chosen_voice_is_kept_and_trimmed(self):
        config = TextToSpeechConfig(provider="elevenlabs", model="eleven_v4", voice=" abc123 ")

        assert config.resolved_voice() == "abc123"

    @pytest.mark.parametrize(
        ("config", "says"),
        [
            ({"provider": "openai", "model": "tts-9"}, "cannot speak"),
            ({"provider": "anthropic", "model": "gpt-4o-mini-tts"}, "cannot speak"),
            ({"provider": "elevenlabs", "model": "eleven_v4"}, "belong to your account"),
            (
                {"provider": "elevenlabs", "model": "eleven_v4", "voice": "  "},
                "belong to your account",
            ),
            ({"provider": "elevenlabs", "model": "eleven_v4", "voice": ".."}, "is not a voice id"),
            ({"provider": "openai", "model": "tts-1", "voice": "marin"}, "has no voice"),
            (
                {"provider": "openai", "model": "tts-1", "voices": [{"id": "marin"}]},
                "has no voice 'marin'",
            ),
            (
                {
                    "provider": "elevenlabs",
                    "model": "eleven_v4",
                    "voice": "abc123",
                    "voices": [{"id": "a b"}],
                },
                "is not a voice id",
            ),
            (
                {
                    "provider": "openai",
                    "model": "gpt-4o-mini-tts",
                    "voices": [{"id": "cedar"}] * 21,
                },
                "at most 20",
            ),
            (
                {
                    "provider": "openai",
                    "model": "gpt-4o-mini-tts",
                    "voices": [{"id": "cedar", "note": "x" * 121}],
                },
                "at most 120",
            ),
            (
                {
                    "provider": "elevenlabs",
                    "model": "eleven_v4",
                    "voice": "abc123",
                    "voices": [{"id": "def456", "note": "Anna"}, {"id": " def456", "note": "Igor"}],
                },
                "listed once",
            ),
            (
                {"provider": "google", "model": "gemini-3.8-flash-tts", "output_format": "mp3"},
                "not mp3",
            ),
        ],
        ids=[
            "unknown model",
            "provider that cannot speak",
            "no voice",
            "blank voice",
            "dots for a voice id",
            "voice the model lacks",
            "other voice the model lacks",
            "other voice not an id",
            "too many voices",
            "a note past a few words",
            "a voice listed twice",
            "format",
        ],
    )
    def test_a_choice_the_provider_would_refuse_is_refused_here(self, config, says):
        with pytest.raises(ValidationError, match=says):
            TextToSpeechConfig(**config)

    def test_with_no_other_voices_only_the_usual_one_is_offered(self):
        config = TextToSpeechConfig(provider="openai", model="tts-1")

        assert config.offered_voices() == (OfferedVoice("alloy", "Alloy"),)

    def test_catalog_voices_are_described_by_the_catalog_and_listed_once(self):
        """The usual voice first, a repeat of it dropped, and a note on a catalog
        voice ignored - the catalog already says what it is."""
        config = TextToSpeechConfig(
            provider="openai",
            model="gpt-4o-mini-tts",
            voice="cedar",
            voices=[{"id": "alloy", "note": "ignored"}, {"id": "cedar"}, {"id": "marin"}],
        )

        assert config.offered_voices() == (
            OfferedVoice("cedar", "Cedar, OpenAI's recommendation for the best quality."),
            OfferedVoice("alloy", "Alloy"),
            OfferedVoice("marin", "Marin, OpenAI's recommendation for the best quality."),
        )

    def test_an_account_voice_is_described_only_by_its_authors_note(self):
        config = TextToSpeechConfig(
            provider="elevenlabs",
            model="eleven_v4",
            voice="narrator1",
            voices=[{"id": " villain2 ", "note": "Igor, the villain"}, {"id": "extra3"}],
        )

        assert config.offered_voices() == (
            OfferedVoice("narrator1"),
            OfferedVoice("villain2", "Igor, the villain"),
            OfferedVoice("extra3"),
        )

    def test_a_provider_dropped_after_validation_is_said_rather_than_guessed(self, monkeypatch):
        config = TextToSpeechConfig()
        monkeypatch.setattr(text_to_speech_models, "CATALOG", ())

        with pytest.raises(ValueError, match="no longer offered"):
            config.resolved_format()

    def test_a_model_dropped_after_validation_is_said_rather_than_guessed(self, monkeypatch):
        config = TextToSpeechConfig()
        openai = text_to_speech_models.CATALOG[0]
        monkeypatch.setattr(
            text_to_speech_models, "CATALOG", (replace(openai, models=openai.models[1:]),)
        )

        with pytest.raises(ValueError, match="no longer offered"):
            config.resolved_voice()


def test_the_key_picker_narrows_to_the_chosen_provider():
    """`required_when` on the provider is what tells the Builder the provider *is*
    the key's purpose (#2258); every provider needs one, so it never relaxes."""
    requirement = get("text_to_speech").secret
    assert requirement is not None and requirement.required_when is not None
    assert requirement.required_when.field == "provider"
    assert set(requirement.required_when.equals) == {
        entry.provider for entry in text_to_speech_models.providers()
    }


def test_the_builder_reads_the_key_and_resolves_voice_and_format():
    definition = get("text_to_speech")
    binding = CapabilityBinding(
        capability_id="text_to_speech",
        config={"provider": "google", "model": "gemini-3.8-flash-lite-tts"},
    )
    built = definition.builder(
        CapabilityBuildContext(
            binding=binding,
            config=definition.validate_config(binding.config),
            resources={},
            secret=ApiKeySecret(api_key="sk-gemini"),
        )
    )

    assert isinstance(built, TextToSpeech)
    assert (built.provider, built.voice, built.audio_format) == ("google", "Kore", "wav")
    assert [offered.id for offered in built.voices] == ["Kore"]
    assert built.api_key == "sk-gemini"
    assert "sk-gemini" not in repr(built)


def test_without_a_config_or_key_it_builds_on_the_defaults():
    definition = get("text_to_speech")
    built = definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="text_to_speech", config={}),
            config=None,
            resources={},
            secret=None,
        )
    )

    assert isinstance(built, TextToSpeech)
    assert built.api_key is None


def test_clips_are_spoken_one_at_a_time():
    """The budget check reserves nothing, so two clips priced together could each
    fit and together pass a cap; running them one at a time is the guard."""
    toolset = _toolset()

    assert toolset.tools["generate_speech"].sequential is True


def test_the_capability_builds_its_toolset_once_and_offers_generate_speech():
    capability = TextToSpeech(
        provider="openai",
        model="gpt-4o-mini-tts",
        voice="marin",
        voices=(OfferedVoice("marin"),),
        audio_format="mp3",
        max_characters=10,
    )

    toolset = capability.get_toolset()

    assert capability.get_toolset() is toolset
    assert list(toolset.tools) == ["generate_speech"]


class TestSpeaking:
    async def test_stores_the_clip_meters_it_and_returns_a_reference(self, synthesis):
        ledger = SpendLedger()
        with metered_by(ledger):
            result = await _speak(
                _toolset(), _ctx(uuid4()), "  Dzień dobry.  ", instructions="calm"
            )

        speech = parse_generated_speech(result)
        assert speech is not None
        assert speech.media_type == "audio/mpeg"
        assert (speech.voice, speech.characters) == ("marin", 12)
        assert speech.filename is not None and speech.filename.endswith("_speech.mp3")
        assert speech.url == f"/api/v1/generated/{speech.filename}"
        [call] = synthesis.calls
        assert (call["text"], call["instructions"], call["api_key"]) == (
            "Dzień dobry.",
            "calm",
            "sk-speech",
        )
        [entry] = ledger.entries
        assert entry.model_name == "openai:gpt-4o-mini-tts"
        assert entry.cost_usd == _price("openai", "gpt-4o-mini-tts") * 12

    async def test_a_wav_clip_is_typed_as_wav(self, synthesis):
        result = await _speak(_toolset(audio_format="wav"), _ctx(uuid4()))

        speech = parse_generated_speech(result)
        assert speech is not None and speech.media_type == "audio/wav"
        assert speech.filename is not None and speech.filename.endswith("_speech.wav")

    async def test_the_clip_is_also_written_into_an_open_workspace(self, synthesis):
        document = StateBackend()
        result = await _speak(_toolset(), _ctx(uuid4(), workspace=document_workspace(document)))

        speech = parse_generated_speech(result)
        assert speech is not None and speech.workspace_path is not None
        assert speech.workspace_path.startswith(f"{WORKSPACE_OUTPUT_DIR}/")
        assert document.read_bytes(speech.workspace_path) == MP3

    async def test_a_sandbox_that_will_not_open_still_hands_back_the_clip(self, synthesis):
        """The sandbox service answering 502 on `POST /sessions` failed the whole
        turn: the clip was spoken, paid for and stored, and lost with the turn."""
        workspace = SandboxUnreachable(document_workspace())

        speech = parse_generated_speech(
            await _speak(_toolset(), _ctx(uuid4(), workspace=workspace))
        )

        assert speech is not None and speech.url is not None
        assert speech.workspace_path is None

    async def test_without_an_organization_the_clip_is_made_but_not_stored(self, synthesis):
        speech = parse_generated_speech(await _speak(_toolset(), _ctx(None)))

        assert speech is not None
        assert (speech.filename, speech.url, speech.workspace_path) == (None, None, None)


@pytest.mark.security
class TestChoosingTheVoice:
    VOICES = (OfferedVoice("marin", "Marin, the narrator"), OfferedVoice("cedar"))

    async def test_another_offered_voice_speaks_and_is_said(self, synthesis):
        result = await _speak(_toolset(voices=self.VOICES), _ctx(uuid4()), voice="cedar")

        speech = parse_generated_speech(result)
        assert speech is not None and speech.voice == "cedar"
        assert synthesis.calls[0]["voice"] == "cedar"

    async def test_left_out_the_usual_voice_speaks(self, synthesis):
        await _speak(_toolset(voices=self.VOICES), _ctx(uuid4()))

        assert synthesis.calls[0]["voice"] == "marin"

    async def test_a_voice_the_author_did_not_offer_names_those_it_did(self, synthesis):
        with pytest.raises(ModelRetry, match="must be one of marin, cedar"):
            await _speak(_toolset(voices=self.VOICES), _ctx(uuid4()), voice="alloy")
        assert synthesis.calls == []

    async def test_with_one_voice_it_says_to_leave_the_voice_out(self, synthesis):
        with pytest.raises(ModelRetry, match="only in marin; leave `voice` out"):
            await _speak(_toolset(), _ctx(uuid4()), voice="cedar")
        assert synthesis.calls == []

    async def test_the_schema_offers_the_voices_with_what_each_is_for(self):
        tools = await _toolset(voices=self.VOICES).get_tools(_ctx(uuid4()))

        voice = tools["generate_speech"].tool_def.parameters_json_schema["properties"]["voice"]
        assert voice["enum"] == ["marin", "cedar"]
        assert voice["default"] == "marin"
        assert voice["description"].endswith(
            "The usual one is marin. Offered: marin: Marin, the narrator."
        )

    async def test_with_one_voice_the_schema_offers_no_choice(self):
        tools = await _toolset().get_tools(_ctx(uuid4()))

        assert "voice" not in tools["generate_speech"].tool_def.parameters_json_schema["properties"]


class TestRefusingBeforeSpending:
    async def test_without_a_key(self, synthesis):
        with pytest.raises(ModelRetry, match="no API key"):
            await _speak(_toolset(api_key=None), _ctx(uuid4()))
        assert synthesis.calls == []

    async def test_blank_text(self, synthesis):
        with pytest.raises(ModelRetry, match="empty"):
            await _speak(_toolset(), _ctx(uuid4()), "   ")
        assert synthesis.calls == []

    async def test_a_direction_longer_than_a_direction_is_refused(self, synthesis):
        """It goes to the provider with every piece and is not priced."""
        with pytest.raises(ModelRetry, match="at most 1000 characters"):
            await _speak(_toolset(), _ctx(uuid4()), instructions="x" * 1001)
        assert synthesis.calls == []

    async def test_text_over_the_limit_names_the_limit(self, synthesis):
        with pytest.raises(ModelRetry, match="at most 100 in one call"):
            await _speak(_toolset(), _ctx(uuid4()), "x" * 101)
        assert synthesis.calls == []

    async def test_on_the_last_attempt_the_steer_is_the_answer(self, synthesis):
        result = await _speak(_toolset(), _ctx(uuid4(), retry=1), "   ")

        assert "empty" in result

    async def test_a_model_the_catalog_has_since_dropped(self, synthesis, monkeypatch):
        monkeypatch.setattr(text_to_speech_models, "CATALOG", ())

        result = await _speak(_toolset(), _ctx(uuid4()))

        assert result.startswith("Not spoken: this agent's speech model is no longer offered")
        assert synthesis.calls == []

    async def test_a_clip_that_would_pass_the_cap_is_refused_with_its_price(self, synthesis):
        """Speech is priced per character, so the clip's cost is known before it is
        made and a run is refused one that would carry it past its cap."""
        price = _price("openai", "gpt-4o-mini-tts")
        text = "x" * 100
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=price * 99)],
        )
        with guarded_by(guard):
            result = await _speak(_toolset(), _ctx(uuid4()), text)

        assert result == (
            f"Not spoken: this clip would cost about ${price * 100:.4f}, more than the "
            "budget this run has left."
        )
        assert synthesis.calls == []

    async def test_an_unpriced_clip_is_refused_once_the_budget_is_spent(
        self, synthesis, monkeypatch
    ):
        monkeypatch.setattr(toolset_module, "price_per_character", lambda *_a, **_k: None)
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.ORGANIZATION, limit_usd=Decimal(0))],
        )
        with guarded_by(guard):
            result = await _speak(_toolset(), _ctx(uuid4()))

        assert result == "Not spoken: this run has spent its budget."
        assert synthesis.calls == []

    async def test_an_unpriced_clip_is_spoken_and_booked_as_unpriced(self, synthesis, monkeypatch):
        monkeypatch.setattr(toolset_module, "price_per_character", lambda *_a, **_k: None)
        ledger = SpendLedger()
        with metered_by(ledger):
            await _speak(_toolset(), _ctx(uuid4()))

        assert ledger.has_unpriced_models is True


class TestAFailedCall:
    @pytest.mark.parametrize(
        ("failure", "answer"),
        [
            (SpeechFailure.CREDENTIALS, "refused this agent's API key"),
            (SpeechFailure.NOT_FOUND, "does not know this agent's voice"),
        ],
    )
    async def test_the_authors_problem_is_answered_not_retried(self, synthesis, failure, answer):
        synthesis.error = SpeechProviderError(failure, provider="openai", status=401)

        result = await _speak(_toolset(), _ctx(uuid4()))

        assert result.startswith("Not spoken:") and answer in result

    async def test_refused_text_is_steered_back_to_the_model(self, synthesis):
        synthesis.error = SpeechProviderError(SpeechFailure.REJECTED, provider="openai", status=400)

        with pytest.raises(ModelRetry, match="Rephrase or shorten the text"):
            await _speak(_toolset(), _ctx(uuid4()))

    @pytest.mark.parametrize("failure", [SpeechFailure.RATE_LIMITED, SpeechFailure.UNAVAILABLE])
    async def test_a_transient_failure_is_worth_one_more_try(self, synthesis, failure):
        synthesis.error = SpeechProviderError(failure, provider="openai")

        with pytest.raises(ModelRetry, match="Try once more"):
            await _speak(_toolset(), _ctx(uuid4()))

    async def test_pieces_spoken_before_a_failure_are_booked(self, synthesis):
        """The half-clip is discarded; the provider's charge for it is not."""
        synthesis.error = SpeechProviderError(
            SpeechFailure.UNAVAILABLE, provider="openai", status=500
        )
        synthesis.spoken_before_error = 40
        ledger = SpendLedger()
        with metered_by(ledger), pytest.raises(ModelRetry):
            await _speak(_toolset(), _ctx(uuid4()), "y" * 80)

        [entry] = ledger.entries
        assert entry.cost_usd == _price("openai", "gpt-4o-mini-tts") * 40

    async def test_a_failure_before_anything_was_spoken_books_nothing(self, synthesis):
        synthesis.error = SpeechProviderError(SpeechFailure.CREDENTIALS, provider="openai")
        ledger = SpendLedger()
        with metered_by(ledger):
            await _speak(_toolset(), _ctx(uuid4()))

        assert ledger.entries == []


def test_parse_generated_speech_rejects_other_results():
    assert parse_generated_speech("Not spoken: no.") is None
    assert parse_generated_speech('{"kind": "generated_image", "media_type": "image/png"}') is None
