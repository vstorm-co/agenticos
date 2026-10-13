"""Which providers are offered for transcription, and which are dropped.

The catalog is a file, and a file can be wrong. Every test here is about an entry
that must *not* reach a picker: a picker entry that fails when somebody sends a
voice note is worse than one that is absent, because the person who chose it is
not the person waiting for an answer.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.agents.model_resolver import PROVIDERS
from app.core.secret_kinds import SecretKind
from app.services import speech_to_text


class TestWhatTheCatalogOffers:
    def test_every_offered_provider_is_one_the_platform_knows(self):
        for entry in speech_to_text.providers():
            assert entry.provider in PROVIDERS

    def test_every_offered_provider_takes_a_plain_api_key(self):
        """The client sends one `Authorization: Bearer`, so a provider wanting a
        service account or an AWS pair would fail on its first call."""
        for entry in speech_to_text.providers():
            assert PROVIDERS[entry.provider].secret_kind is SecretKind.API_KEY

    def test_every_offered_provider_has_an_address_and_a_model(self):
        for entry in speech_to_text.providers():
            assert entry.base_url.startswith("https://")
            assert entry.models

    def test_model_ids_are_unique_within_a_provider(self):
        for entry in speech_to_text.providers():
            ids = [model.id for model in entry.models]
            assert len(ids) == len(set(ids))

    def test_each_model_says_when_to_reach_for_it(self):
        """The description is what a picker renders under the name; an empty one
        makes the entry a name somebody has to guess about."""
        for entry in speech_to_text.providers():
            for model in entry.models:
                assert model.name
                assert len(model.description) > 20


class TestWhatIsDropped:
    def test_an_entry_naming_an_unknown_provider(self, monkeypatch):
        unknown = replace(speech_to_text.CATALOG[0], provider="not-a-provider")
        monkeypatch.setattr(speech_to_text, "CATALOG", (unknown,))

        assert speech_to_text.providers() == ()

    def test_an_entry_with_no_models(self, monkeypatch):
        empty = replace(speech_to_text.CATALOG[0], models=())
        monkeypatch.setattr(speech_to_text, "CATALOG", (empty,))

        assert speech_to_text.providers() == ()

    def test_an_entry_whose_api_shape_has_no_client(self, monkeypatch):
        """The field is what says how to call it, so an unimplemented shape is a
        dropped entry rather than a call nobody wrote."""
        future = replace(speech_to_text.CATALOG[0], api="realtime")
        monkeypatch.setattr(speech_to_text, "CATALOG", (future,))

        assert speech_to_text.providers() == ()

    def test_an_entry_whose_credential_is_not_a_key(self, monkeypatch):
        """Bedrock and Vertex can be model providers here and cannot be reached
        with a bearer token."""
        needs_more = replace(speech_to_text.CATALOG[0], provider="bedrock")
        monkeypatch.setattr(speech_to_text, "CATALOG", (needs_more,))

        assert speech_to_text.providers() == ()


class TestChoosingOne:
    def test_a_catalogued_model_is_offered(self):
        provider = speech_to_text.providers()[0]

        assert speech_to_text.is_offered(provider.provider, provider.models[0].id)

    def test_a_model_the_catalog_does_not_list_is_not(self):
        """Refused at the form rather than when somebody sends a voice note."""
        provider = speech_to_text.providers()[0]

        assert not speech_to_text.is_offered(provider.provider, "whisper-tiny-imaginary")

    def test_a_provider_that_cannot_transcribe_is_not(self):
        assert not speech_to_text.is_offered("anthropic", "whisper-1")

    def test_the_default_follows_the_catalog_rather_than_a_constant(self):
        """So moving the file's first entry moves the default, instead of leaving
        an id repeated in two places that have to change together."""
        first = speech_to_text.providers()[0]

        assert speech_to_text.default_choice() == (first.provider, first.models[0].id)

    def test_there_is_no_default_when_nothing_is_offered(self, monkeypatch):
        """Not an error and not a guess: a build whose providers all want service
        accounts offers no transcription, and the caller has to say so."""
        monkeypatch.setattr(speech_to_text, "CATALOG", ())

        assert speech_to_text.default_choice() is None

    def test_by_provider_answers_none_rather_than_raising(self):
        assert speech_to_text.by_provider("anthropic") is None


@pytest.mark.parametrize("provider", ["openai", "groq", "mistral"])
def test_the_providers_this_shipped_with_stay_offered(provider: str):
    """A regression guard on the file, not a restatement of it: these three are
    what the feature was built and documented against, so losing one to a typo or
    a provider rename should fail here rather than in somebody's chat."""
    assert speech_to_text.by_provider(provider) is not None
