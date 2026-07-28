"""Which models a provider offers, and what happens when it will not say.

The field this fills is free text and always will be - providers ship models
faster than any list here is refreshed. So the only thing worth guarding is that
the suggestions are *right when they exist* and *absent rather than wrong when
they do not*: a dropdown of ids the provider does not serve is worse than an
empty one, because each is a run that fails with an authentication-shaped error.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import model_catalog
from app.services.model_catalog import CURATED, LISTINGS, models_for

MODULE = "app.services.model_catalog"


@pytest.fixture(autouse=True)
def _empty_cache():
    model_catalog.clear_cache()
    yield
    model_catalog.clear_cache()


def _responds(payload: object) -> MagicMock:
    """An `httpx.AsyncClient` whose one GET answers with this body."""
    response = MagicMock(json=MagicMock(return_value=payload), raise_for_status=MagicMock())
    client = MagicMock(get=AsyncMock(return_value=response))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestReadingAListing:
    @pytest.mark.anyio
    async def test_openrouter_is_read_without_a_key(self):
        """Its listing is public, which is why it is the one provider a
        deployment can offer suggestions for before anybody has stored anything."""
        payload = {
            "data": [
                {"id": "anthropic/claude-opus-5", "name": "Claude Opus 5", "context_length": 1000000}
            ]
        }
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=_responds(payload)):
            models, source = await models_for("openrouter")

        assert source == "live"
        assert models[0].id == "anthropic/claude-opus-5"
        assert models[0].context_length == 1000000

    @pytest.mark.anyio
    async def test_a_prefix_the_provider_adds_is_stripped(self):
        """Gemini answers `models/gemini-3.6-flash` and expects the bare id back;
        sending what it listed is a 404 from the model endpoint."""
        payload = {"models": [{"name": "models/gemini-3.6-flash", "displayName": "Flash"}]}
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=_responds(payload)):
            models, _ = await models_for("google", api_key="k")

        assert models[0].id == "gemini-3.6-flash"

    @pytest.mark.anyio
    async def test_a_listing_that_is_a_bare_array_is_read(self):
        """Together answers with the array itself rather than wrapping it."""
        payload = [{"id": "moonshotai/Kimi-K3", "display_name": "Kimi K3"}]
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=_responds(payload)):
            models, source = await models_for("together", api_key="k")

        assert source == "live"
        assert models[0].name == "Kimi K3"

    @pytest.mark.anyio
    async def test_a_row_with_no_id_is_skipped_rather_than_failing_the_list(self):
        """One malformed row must not cost the other three hundred."""
        payload = {"data": [{"name": "no id here"}, {"id": "openai/gpt-5.6-sol"}]}
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=_responds(payload)):
            models, _ = await models_for("openrouter")

        assert [entry.id for entry in models] == ["openai/gpt-5.6-sol"]

    @pytest.mark.anyio
    async def test_a_model_with_no_display_name_shows_its_id(self):
        """OpenAI's listing is `id` and nothing else."""
        payload = {"data": [{"id": "gpt-5.6-sol"}]}
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=_responds(payload)):
            models, _ = await models_for("openai", api_key="k")

        assert models[0].name == "gpt-5.6-sol"


class TestWhenTheProviderWillNotSay:
    @pytest.mark.anyio
    async def test_no_key_means_the_curated_list_rather_than_a_call(self):
        """Every listing but OpenRouter's needs one, and an organization that has
        not stored a key yet is exactly who is looking at this form."""
        with patch(f"{MODULE}.httpx.AsyncClient") as client:
            models, source = await models_for("anthropic")

        assert source == "curated"
        assert client.call_count == 0
        assert any(entry.id == "claude-opus-5" for entry in models)

    @pytest.mark.anyio
    async def test_a_failed_call_falls_back_instead_of_raising(self):
        """This fills a dropdown. A 502 in a dropdown is the worst of the three
        possible outcomes - worse than stale, and worse than empty."""
        client = _responds({})
        client.get = AsyncMock(side_effect=httpx.ConnectError("no route"))
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=client):
            models, source = await models_for("openrouter")

        assert source == "curated"
        assert models == list(CURATED["openrouter"])

    @pytest.mark.anyio
    async def test_an_empty_listing_is_treated_as_no_answer(self):
        """A provider answering `[]` leaves the field with nothing to suggest,
        and the curated list is a better nothing."""
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=_responds({"data": []})):
            models, source = await models_for("openrouter")

        assert source == "curated"
        assert models

    @pytest.mark.anyio
    async def test_a_provider_with_no_listing_and_no_curation_answers_empty(self):
        """Not an error: the field is free text, and a self-hosted endpoint
        nobody has a list for is the case it was built for."""
        models, source = await models_for("some-self-hosted-thing")

        assert (models, source) == ([], "curated")


class TestCaching:
    @pytest.mark.anyio
    async def test_a_second_ask_does_not_call_the_provider_again(self):
        """These lists move on the order of weeks; a call per form open is a
        call per keystroke away from being a call per keystroke."""
        client = _responds({"data": [{"id": "openai/gpt-5.6-sol"}]})
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=client):
            await models_for("openrouter")
            await models_for("openrouter")

        assert client.get.await_count == 1

    @pytest.mark.anyio
    async def test_the_cache_is_keyed_on_the_provider_and_not_on_the_key(self):
        """Two keys for one provider see the same catalog, and a cache keyed on
        the key would put a secret in a dictionary key."""
        client = _responds({"data": [{"id": "gpt-5.6-sol"}]})
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=client):
            await models_for("openai", api_key="first")
            await models_for("openai", api_key="second")

        assert client.get.await_count == 1


class TestTheCuratedList:
    def test_every_curated_provider_is_one_this_platform_can_run(self):
        """A curated id for a provider the resolver cannot build is a suggestion
        that cannot be acted on."""
        from app.agents.model_resolver import PROVIDERS

        assert set(CURATED) <= set(PROVIDERS)

    def test_every_listed_provider_is_one_this_platform_can_run(self):
        from app.agents.model_resolver import PROVIDERS

        assert set(LISTINGS) <= set(PROVIDERS)

    def test_openrouter_ids_are_namespaced_and_the_others_are_not(self):
        """The one rule this platform enforces on a model id, kept true of the
        suggestions it makes - otherwise the form refuses its own dropdown."""
        assert all("/" in entry.id for entry in CURATED["openrouter"])
        assert all("/" not in entry.id for entry in CURATED["anthropic"])
