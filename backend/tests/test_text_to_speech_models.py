"""Which providers are offered for speech, with which voices, and at what price.

The catalog is a file, and a file can be wrong. Most tests here are about an entry
that must *not* reach a picker, because one that fails on its first call is worse
than one that is absent; the rest are about the price a budget is checked against,
which is the number that stops a run.
"""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core import secret_purposes
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import SecretKind
from app.main import app
from app.services import text_to_speech_models
from app.services.text_to_speech_models import SpeechPrice, piece_cost, price_per_character


def _provider(provider_id: str) -> text_to_speech_models.TextToSpeechProvider:
    entry = text_to_speech_models.by_provider(provider_id)
    assert entry is not None
    return entry


class TestWhatTheCatalogOffers:
    def test_every_offered_provider_can_be_keyed_with_a_plain_api_key(self):
        """The capability seals one API key; a provider the vault cannot store one
        for is a picker entry nobody can use."""
        for entry in text_to_speech_models.providers():
            purpose = secret_purposes.get(entry.provider)
            assert purpose is not None
            assert purpose.kind is SecretKind.API_KEY

    def test_every_offered_provider_has_an_address_a_format_and_a_model(self):
        for entry in text_to_speech_models.providers():
            assert entry.base_url.startswith("https://")
            assert entry.formats
            assert entry.models

    def test_ids_are_unique_within_a_provider(self):
        for entry in text_to_speech_models.providers():
            models = [model.id for model in entry.models]
            voices = [voice.id for voice in entry.voices]
            assert len(models) == len(set(models))
            assert len(voices) == len(set(voices))

    def test_each_model_says_when_to_reach_for_it_and_what_it_costs(self):
        for entry in text_to_speech_models.providers():
            for model in entry.models:
                assert len(model.description) > 20
                assert model.max_characters > 0
                assert price_per_character(model, on=date(2026, 10, 20)) is not None

    def test_a_model_limited_to_some_voices_names_only_voices_the_provider_has(self):
        """A restriction naming a voice that is not listed would leave the model
        with a picker entry that the provider refuses."""
        for entry in text_to_speech_models.providers():
            known = {voice.id for voice in entry.voices}
            for model in entry.models:
                assert set(model.voices) <= known

    def test_the_older_openai_models_speak_in_only_some_voices(self):
        openai = _provider("openai")
        tts_1 = openai.model("tts-1")
        assert tts_1 is not None

        voices = {voice.id for voice in openai.voices_for(tts_1)}

        assert "alloy" in voices
        assert "marin" not in voices

    def test_a_model_with_no_restriction_speaks_in_every_voice(self):
        openai = _provider("openai")
        mini = openai.model("gpt-4o-mini-tts")
        assert mini is not None

        assert openai.voices_for(mini) == openai.voices

    def test_elevenlabs_voices_belong_to_the_account(self):
        """Its shared defaults expire on 2026-12-31, so the catalog lists none and a
        binding names one of the account's own voices by id."""
        elevenlabs = _provider("elevenlabs")

        assert elevenlabs.voices == ()
        assert elevenlabs.account_voices is True
        assert _provider("openai").account_voices is False

    def test_an_unlisted_model_id_is_not_a_model(self):
        assert _provider("openai").model("tts-imaginary") is None


class TestWhatIsDropped:
    @pytest.mark.parametrize(
        "change",
        [
            {"provider": "not-a-service"},
            # Bedrock is a purpose, and its credential is an AWS pair, not a key.
            {"provider": "bedrock"},
            {"models": ()},
            {"formats": ()},
            {"api": "websocket"},
        ],
        ids=["unknown provider", "not a plain key", "no models", "no formats", "no client"],
    )
    def test_an_entry_that_would_fail_on_its_first_call(self, monkeypatch, change):
        broken = replace(text_to_speech_models.CATALOG[0], **change)
        monkeypatch.setattr(text_to_speech_models, "CATALOG", (broken,))

        assert text_to_speech_models.providers() == ()


class TestChoosingOne:
    def test_a_provider_that_cannot_speak_is_not_offered(self):
        assert text_to_speech_models.by_provider("anthropic") is None

    def test_the_default_follows_the_catalog_rather_than_a_constant(self):
        first = text_to_speech_models.providers()[0]

        assert text_to_speech_models.default_choice() == (first.provider, first.models[0].id)


class TestPrices:
    def test_a_scheduled_price_takes_effect_on_its_day(self):
        """Gemini's speech prices double on 2027-01-01; a budget still checking the
        old one would let a run spend twice what its cap says."""
        flash = _provider("google").model("gemini-3.8-flash-tts")
        assert flash is not None

        before = price_per_character(flash, on=date(2026, 12, 31))
        after = price_per_character(flash, on=date(2027, 1, 1))

        assert before == Decimal("15.1") / 1_000_000
        assert after == Decimal("30.2") / 1_000_000

    def test_the_latest_started_price_wins_whatever_the_file_order(self):
        model = replace(
            _provider("openai").models[0],
            prices=(
                SpeechPrice(since=date(2026, 6, 1), usd_per_million_characters=Decimal("20")),
                SpeechPrice(since=date(2026, 1, 1), usd_per_million_characters=Decimal("10")),
            ),
        )

        assert price_per_character(model, on=date(2026, 7, 1)) == Decimal("20") / 1_000_000

    def test_before_any_price_started_the_call_is_unpriced_rather_than_free(self):
        model = replace(
            _provider("openai").models[0],
            prices=(SpeechPrice(since=date(2030, 1, 1), usd_per_million_characters=Decimal("1")),),
        )

        assert price_per_character(model, on=date(2026, 10, 20)) is None
        assert piece_cost(model, on=date(2026, 10, 20), characters=10, seconds=1.0) is None


class TestPieceCost:
    """What a spoken piece is booked at, after its audio came back (#2351)."""

    def test_a_token_billed_piece_is_booked_from_its_audio(self):
        """Gemini bills text tokens in and 25 audio tokens a second out."""
        flash = _provider("google").model("gemini-3.8-flash-tts")
        assert flash is not None

        cost = piece_cost(flash, on=date(2026, 10, 20), characters=400, seconds=10.0)

        # 100 text tokens at $0.50/M and 250 audio tokens at $9.00/M.
        assert cost == (100 * Decimal("0.50") + 250 * Decimal("9.00")) / 1_000_000

    def test_a_slow_delivery_of_the_same_text_costs_more(self):
        flash = _provider("google").model("gemini-3.8-flash-tts")
        assert flash is not None

        brisk = piece_cost(flash, on=date(2026, 10, 20), characters=400, seconds=5.0)
        slow = piece_cost(flash, on=date(2026, 10, 20), characters=400, seconds=20.0)

        assert brisk is not None and slow is not None and slow > 3 * brisk

    def test_the_rates_follow_the_scheduled_price(self):
        flash = _provider("google").model("gemini-3.8-flash-tts")
        assert flash is not None

        before = piece_cost(flash, on=date(2026, 12, 31), characters=0, seconds=10.0)
        after = piece_cost(flash, on=date(2027, 1, 1), characters=0, seconds=10.0)

        assert before is not None and after == 2 * before

    @pytest.mark.parametrize(
        ("provider", "model", "seconds"),
        [("openai", "tts-1", 3.0), ("google", "gemini-3.8-flash-tts", None)],
        ids=["character-billed", "length-unknown"],
    )
    def test_otherwise_a_piece_is_booked_by_its_characters(self, provider, model, seconds):
        chosen = _provider(provider).model(model)
        assert chosen is not None

        cost = piece_cost(chosen, on=date(2026, 10, 20), characters=300, seconds=seconds)

        assert cost == price_per_character(chosen, on=date(2026, 10, 20)) * 300

    def test_a_price_states_all_three_token_rates_or_none(self):
        with pytest.raises(ValueError, match="all three token rates"):
            SpeechPrice(
                since=date(2026, 1, 1),
                usd_per_million_characters=Decimal("1"),
                usd_per_million_audio_tokens=Decimal("9"),
            )


@pytest.mark.parametrize("provider", ["openai", "elevenlabs", "google"])
def test_the_providers_this_shipped_with_stay_offered(provider: str):
    """What #2259 was built and documented against; losing one to a typo or a
    purpose rename should fail here rather than in somebody's chat."""
    assert text_to_speech_models.by_provider(provider) is not None


@pytest.mark.anyio
async def test_the_builder_reads_voices_per_model_and_whether_they_are_the_accounts(
    client: AsyncClient,
):
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )

    response = await client.get("/api/v1/providers/text-to-speech-models")

    assert response.status_code == 200
    body = response.json()
    providers = {item["provider"]: item for item in body["items"]}
    assert body["total"] == len(providers)
    assert providers["elevenlabs"]["account_voices"] is True
    assert providers["google"]["formats"] == ["wav"]
    openai_models = {model["id"]: model for model in providers["openai"]["models"]}
    assert "marin" not in {voice["id"] for voice in openai_models["tts-1"]["voices"]}
    assert openai_models["gpt-4o-mini-tts"]["takes_instructions"] is True
