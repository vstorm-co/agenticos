"""The catalog of providers a collection can embed through.

Every entry is a claim this build will act on: an address it will POST a
credential to, and a set of models it will let a collection be created at. So
the file is checked the way `image_models.json` is - a provider that cannot be
keyed, or a model whose width nothing else agrees with, is an entry that fails
on its first document rather than at import.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.core import secret_purposes
from app.core.exceptions import BadRequestError
from app.services.rag import embedding_providers
from app.services.rag.config import EMBEDDING_DIMENSIONS

_OLLAMA = "http://ollama:11434/v1"


@contextmanager
def _deployment(*, ollama: str) -> Iterator[None]:
    """The deployment's say in the catalog: where, if anywhere, its Ollama is."""
    with patch(
        "app.services.rag.embedding_providers.settings",
        MagicMock(EMBEDDING_OLLAMA_BASE_URL=ollama),
    ):
        yield


class TestTheCatalog:
    def test_no_provider_claims_a_deployment_key(self):
        """There is no deployment-wide embedding credential: every collection
        pays with a vault key of its own, so the catalog states addresses and
        models and nothing about whose key applies where."""
        for entry in embedding_providers.providers():
            assert not hasattr(entry, "deployment_key")

    def test_every_keyed_provider_is_a_purpose_a_key_can_be_stored_for(self):
        """A collection's key is a vault entry whose purpose is the provider id.
        A provider nothing can be keyed for is a provider no collection could
        ever pay for. A keyless one is paid by nobody, so it needs no purpose."""
        purposes = {entry.id for entry in secret_purposes.all_purposes()}
        keyed = {entry.provider for entry in embedding_providers.providers() if not entry.keyless}

        assert keyed <= purposes

    def test_a_keyed_provider_states_a_vendor_address_and_a_keyless_one_states_none(self):
        """The file cannot know where somebody's Ollama runs, so a keyless entry
        carries no address and the deployment supplies one; a keyed entry is a
        vendor across the internet, reached over TLS."""
        for entry in embedding_providers.CATALOG:
            if entry.keyless:
                assert entry.base_url is None
                assert entry.provider in embedding_providers._DEPLOYMENT_ADDRESSES
            else:
                assert entry.base_url is not None
                assert entry.base_url.startswith("https://")


class TestAKeylessProvider:
    def test_is_offered_only_where_the_deployment_names_its_address(self):
        """An entry with nowhere to send the request is a collection that cannot
        index its first document, so an unset address hides the entry rather
        than offering it (#1632)."""
        with _deployment(ollama=""):
            assert embedding_providers.get("ollama") is None
            assert "ollama" not in {entry.provider for entry in embedding_providers.providers()}
        with _deployment(ollama=_OLLAMA):
            offered = embedding_providers.get("ollama")

        assert offered is not None
        assert offered.keyless
        assert offered.base_url == _OLLAMA

    def test_the_address_is_the_deployments_not_the_files(self):
        with _deployment(ollama="  http://gpu-box:11434/v1 "):
            offered = embedding_providers.require("ollama", model="nomic-embed-text", dim=768)

        assert offered.base_url == "http://gpu-box:11434/v1"

    def test_a_keyed_provider_is_offered_whatever_the_deployment_set(self):
        with _deployment(ollama=""):
            assert embedding_providers.get("openrouter") is not None
            assert embedding_providers.get("openai") is not None

    def test_the_refusal_for_an_unknown_id_lists_only_what_is_offered(self):
        with _deployment(ollama=""), pytest.raises(BadRequestError) as refusal:
            embedding_providers.require("azure", model="text-embedding-3-small", dim=1536)

        assert "ollama" not in refusal.value.message

    def test_every_model_offered_has_the_width_the_rest_of_the_build_uses(self):
        """`EMBEDDING_DIMENSIONS` is what `chosen_embedding` creates the vector
        column at. A catalog claiming another width for the same model would
        create a column one size and write vectors of another."""
        for entry in embedding_providers.providers():
            for model in entry.models:
                assert EMBEDDING_DIMENSIONS.get(model.model) == model.dim

    def test_no_provider_is_listed_twice(self):
        ids = [entry.provider for entry in embedding_providers.providers()]

        assert len(ids) == len(set(ids))


class TestTheFirstEntry:
    def test_the_first_entry_is_openrouter_and_reordering_it_is_a_decision(self):
        """`first()` is what `POST /rag/collections/{name}` records for a
        collection created with no say in the matter. The file's order is
        load-bearing for those rows, so a reorder fails here by name rather
        than quietly changing what a legacy collection embeds through."""
        assert embedding_providers.first().provider == "openrouter"
        assert embedding_providers.first() == embedding_providers.providers()[0]

    def test_a_deployment_with_an_ollama_still_starts_a_legacy_row_on_a_keyed_provider(self):
        """The keyless entry is last in the file on purpose: a legacy row is
        org-scoped and waits for a key, and the first entry is the one it waits
        for a key *for*."""
        with _deployment(ollama=_OLLAMA):
            assert embedding_providers.first().provider == "openrouter"


class TestRequiringOne:
    def test_a_provider_that_serves_the_model_at_its_width_is_returned(self):
        entry = embedding_providers.require("openai", model="text-embedding-3-small", dim=1536)

        assert entry.provider == "openai"
        assert entry.base_url == "https://api.openai.com/v1"

    def test_an_id_this_build_does_not_offer_is_refused_on_the_field(self):
        with pytest.raises(BadRequestError) as refusal:
            embedding_providers.require("azure", model="text-embedding-3-small", dim=1536)

        assert refusal.value.details["fields"][0]["field"] == "embedding_provider"

    def test_a_provider_that_serves_the_model_at_another_width_is_refused(self):
        """The width is the collection's column, not a preference: a provider
        answering 1536 for a model the column holds at 3072 writes vectors that
        either fail or are compared as though they meant the same thing."""
        with pytest.raises(BadRequestError) as refusal:
            embedding_providers.require("openai", model="text-embedding-3-small", dim=3072)

        assert "3072" in refusal.value.message

    def test_a_provider_that_serves_it_answers_with_its_address(self):
        entry = embedding_providers.require("openai", model="text-embedding-3-large", dim=3072)

        assert entry.base_url == "https://api.openai.com/v1"

    def test_serving_is_model_and_width_together(self):
        entry = embedding_providers.get("openai")

        assert entry is not None
        assert entry.serves("text-embedding-3-small", 1536)
        assert not entry.serves("text-embedding-3-small", 3072)
        assert not entry.serves("voyage-3", 1024)

    def test_an_id_nobody_offers_reads_as_absent(self):
        assert embedding_providers.get("a-provider-that-left") is None
