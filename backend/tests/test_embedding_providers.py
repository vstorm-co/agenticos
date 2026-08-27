"""The catalog of providers a collection can embed through.

Every entry is a claim this build will act on: an address it will POST a
credential to, and a set of models it will let a collection be created at. So
the file is checked the way `image_models.json` is - a provider that cannot be
keyed, or a model whose width nothing else agrees with, is an entry that fails
on its first document rather than at import.
"""

from __future__ import annotations

import pytest

from app.core import secret_purposes
from app.core.exceptions import BadRequestError
from app.services.rag import embedding_providers
from app.services.rag.config import EMBEDDING_DIMENSIONS


class TestTheCatalog:
    def test_exactly_one_provider_owns_the_deployments_key(self):
        """`OPENROUTER_API_KEY` is one key and it belongs to one endpoint. Two
        entries claiming it would send it to whichever the file listed first;
        none would leave a deployment with a key and nowhere to use it."""
        owners = [entry for entry in embedding_providers.providers() if entry.deployment_key]

        assert len(owners) == 1
        assert embedding_providers.deployment_provider() is owners[0]

    def test_every_provider_is_a_purpose_a_key_can_be_stored_for(self):
        """A collection's key is a vault entry whose purpose is the provider id.
        A provider nothing can be keyed for is a provider only the deployment's
        own key could pay for."""
        purposes = {entry.id for entry in secret_purposes.all_purposes()}

        assert {entry.provider for entry in embedding_providers.providers()} <= purposes

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


class TestRequiringOne:
    def test_no_provider_named_is_the_deployments_own(self):
        """What a collection created before providers were a choice has."""
        entry = embedding_providers.require(None, model="text-embedding-3-small", dim=1536)

        assert entry is embedding_providers.deployment_provider()

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
