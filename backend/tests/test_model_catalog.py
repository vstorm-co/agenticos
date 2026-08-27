"""Which models a provider offers, and what happens when it will not say.

The field this fills is free text and always will be - providers ship models
faster than any list here is refreshed. So the only thing worth guarding is that
the suggestions are *right when they exist* and *absent rather than wrong when
they do not*: a dropdown of ids the provider does not serve is worse than an
empty one, because each is a run that fails with an authentication-shaped error.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.model_resolver import PROVIDERS
from app.services import model_catalog
from app.services.image_models import CATALOG as IMAGE_CATALOG
from app.services.model_catalog import CURATED, LISTINGS, curated_models, models_for

MODULE = "app.services.model_catalog"


@pytest.fixture(autouse=True)
def _empty_cache():
    model_catalog._cache.clear()
    yield
    model_catalog._cache.clear()


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
                {
                    "id": "anthropic/claude-opus-5",
                    "name": "Claude Opus 5",
                    "context_length": 1000000,
                }
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
        assert models == list(curated_models("openrouter"))

    @pytest.mark.anyio
    async def test_an_empty_listing_is_treated_as_no_answer(self):
        """A provider answering `[]` leaves the field with nothing to suggest,
        and the curated list is a better nothing."""
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=_responds({"data": []})):
            models, source = await models_for("openrouter")

        assert source == "curated"
        assert models

    @pytest.mark.anyio
    async def test_a_failed_call_with_nothing_curated_is_unlisted_too(self):
        """Four paths reach the fallback - no listing, no key, a failed call, an
        empty answer - and they have to agree. `mistral` publishes a listing and
        has no curated entry, so a transient failure used to answer `curated`
        about a shortlist that does not exist (#923)."""
        client = _responds({})
        client.get = AsyncMock(side_effect=httpx.ConnectError("no route"))
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=client):
            models, source = await models_for("mistral", api_key="k")

        assert (models, source) == ([], "unlisted")

    @pytest.mark.anyio
    async def test_an_empty_answer_with_nothing_curated_is_unlisted_as_well(self):
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=_responds({"data": []})):
            models, source = await models_for("mistral", api_key="k")

        assert (models, source) == ([], "unlisted")

    @pytest.mark.anyio
    async def test_a_provider_with_no_listing_and_no_curation_says_it_is_unlisted(self):
        """Not an error: the field is free text, and a self-hosted endpoint
        nobody has a list for is the case it was built for.

        `unlisted` rather than `curated`, because seven providers land here and
        `curated` about an empty list claims a shortlist that does not exist
        (#923). It is the difference between "the provider could not be asked"
        and "this platform cannot enumerate this one at all"."""
        models, source = await models_for("some-self-hosted-thing")

        assert (models, source) == ([], "unlisted")


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


class TestCuratedFallbacksAreData:
    """The suggestions are a catalog file, and the numbers are the library's.

    Both halves were a Python literal with hand-typed context lengths, and both
    rotted the way hand-typed data does: `gemini-3.6-flash` was written as
    1,048,576 here and 1,000,000 by `genai-prices`, and the same model appeared
    twice under two providers with two different figures.
    """

    def test_every_curated_id_is_one_the_price_snapshot_knows(self):
        # This is what the library is for here. A typo or a model the provider has
        # retired fails the build, rather than shipping a dropdown whose value the
        # provider answers 404 to.
        from app.services.model_catalog import CURATED, priced_model

        unknown = [
            f"{provider}:{entry.id}"
            for provider, models in CURATED.items()
            for entry in models
            if priced_model(provider, entry.id) is None
        ]

        assert unknown == []

    def test_a_model_the_snapshot_knows_without_a_window_is_not_a_failure(self):
        # Two of the curated ids are exactly this today - `gemini-3.1-pro-preview`
        # and `llama-3.3-70b-versatile`. "Known but unpriced" is not "unknown", and
        # a null window is what the capability resolves for itself.
        from app.services.model_catalog import context_window, priced_model

        assert priced_model("google", "gemini-3.1-pro-preview") is not None
        assert context_window("google", "gemini-3.1-pro-preview") is None

    def test_a_window_comes_from_the_snapshot_rather_than_from_this_repo(self):
        from app.services.model_catalog import curated_models

        windows = {model.id: model.context_length for model in curated_models("anthropic")}

        assert windows["claude-opus-5"] == 1_000_000
        assert windows["claude-haiku-4-5"] == 200_000

    def test_an_openrouter_id_takes_its_window_from_the_provider_it_names(self):
        # An OpenRouter id is `<provider>/<model>`, and the snapshot prices those
        # rows under the provider rather than under the namespaced spelling.
        from app.services.model_catalog import context_window

        assert context_window("openrouter", "anthropic/claude-opus-5") == 1_000_000

    def test_a_provider_the_snapshot_spells_differently_still_resolves(self):
        # It writes `x-ai`; the platform writes `xai`.
        from app.services.model_catalog import context_window

        assert context_window("xai", "grok-4.5") == 500_000

    def test_a_model_nothing_prices_reads_as_not_recorded(self):
        from app.services.model_catalog import context_window

        assert context_window("anthropic", "claude-imaginary-9") is None
        assert context_window("not-a-provider", "whatever") is None

    def test_the_fallback_carries_no_numbers_of_its_own(self):
        # A `FallbackModel` is an id and a name. Adding a context length back would
        # be adding the field that went stale.
        from app.services.model_catalog import FallbackModel

        assert set(FallbackModel.__dataclass_fields__) == {"id", "name"}

    def test_every_keyed_listing_says_how_to_authenticate(self):
        from app.services.model_catalog import LISTINGS

        for name, spec in LISTINGS.items():
            if spec.auth_header is not None:
                assert "{key}" in spec.auth_template, name

    def test_the_listing_whose_body_is_the_array_survived_the_move_to_json(self):
        # Together answers with the array as the whole body, which `array_path: ""`
        # says - and an empty string is exactly what a generator writing this file
        # is tempted to drop.
        from app.services.model_catalog import LISTINGS

        assert LISTINGS["together"].array_path == ""


def _documented_providers() -> set[str]:
    """The ids in the `| Provider | id | Credential | Custom URL |` tables.

    Read off the second cell of every row under one of those headers, so a row
    added or removed is the thing being compared - and prose elsewhere on the
    page is not.
    """
    page = (Path(__file__).resolve().parents[2] / "docs" / "models.md").read_text()
    ids: set[str] = set()
    in_table = False
    for line in page.splitlines():
        if line.startswith("| Provider | id |"):
            in_table = True
            continue
        if in_table and not line.startswith("|"):
            in_table = False
        if not in_table or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) > 1 and cells[1].startswith("`"):
            ids.add(cells[1].strip("`"))
    return ids


class TestOneAnswerPerQuestion:
    """Which list answers what, and that the derived copies still agree (#923).

    "What models and providers exist" is answered in six places. `PROVIDERS` is
    the one the platform runs on - it holds the part `infer_provider_class`
    cannot know, the credential shape - and every other list is derived from it:
    the listings, the curated shortlist, the image catalog, and the tables in
    `docs/models.md`. A derived copy that drifts fails nothing at run time; it
    shows a picker for a provider that does not exist, or leaves out one that
    does, which is how the tool catalog rendered two tools as raw JSON for five
    weeks (#144).
    """

    def test_every_listing_names_a_provider_the_platform_has(self):
        assert [provider for provider in LISTINGS if provider not in PROVIDERS] == []

    def test_every_curated_entry_names_a_provider_the_platform_has(self):
        assert [provider for provider in CURATED if provider not in PROVIDERS] == []

    def test_every_image_provider_names_one_too(self):
        # A third vocabulary - `image_models.json` carries its own `provider` and
        # `prefix` pair - and the crossing is a lookup that answers `None` for a
        # provider spelled differently.
        assert [entry.provider for entry in IMAGE_CATALOG if entry.provider not in PROVIDERS] == []

    def test_the_documented_provider_table_is_the_provider_table(self):
        """`docs/models.md` is a hand-written copy of `PROVIDERS`, and the repo's
        rule is one copy on purpose. Until it is generated, this is what makes
        adding the twenty-eighth provider a change that fails until the page
        knows about it.

        The **id column of the tables**, not a search of the page for the token:
        a search passes on a removed provider whose row is still there, and on
        an id the prose happens to mention for another reason - the page names
        one it deliberately does not support. Two directions, one comparison.
        """
        assert _documented_providers() == set(PROVIDERS)
