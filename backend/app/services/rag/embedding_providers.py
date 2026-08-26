"""Who can serve a collection's embedding model, and at what address.

A collection's embedding *model* is frozen at creation and has to be: the vector
column is created at that model's width, so a second model's vectors either cannot
be written or are compared against the first model's as though they meant the same
thing. Nothing here changes that.

What was frozen by accident is **whose endpoint answers**. Every embedding request
went to `https://openrouter.ai/api/v1`, hardcoded in `EmbeddingService`, and the
only choice a collection had was which vault key paid for it - so an organization
holding an OpenAI key could not use it, a key rotated onto another account meant
recreating the collection and re-ingesting every document, and a collection could
send one vendor's credential to another vendor's address without anything
objecting.

The provider is a per-collection choice now, and a changeable one, because the
thing that must not change is unaffected: the same model at the same width
produces vectors in the same space wherever it is served from. Swapping the
provider re-points the address and the credential; swapping the model would
invalidate every vector already stored, which is why one is editable and the
other is not.

Which providers, and which of their models, is **data** -
`app/core/catalog/embedding_providers.json` - for the reason `image_models.json`
is: an id, an address and a width per model is not code, and adding a provider
released this quarter should not be a diff in three modules. What interprets an
entry stays here.

An entry states what the provider's own documentation states it serves through an
OpenAI-compatible `/embeddings` route. Two are listed today, and a third is one
file entry: the models nobody can reach - `voyage-3`, the `bge-*` and
`all-MiniLM-*` sentence-transformer weights - were offered by the create form for
months on the strength of a width map, and the width of a model this build cannot
call is not an answer to "can I use it".
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import TypeAdapter

from app.core import catalog
from app.core.field_errors import refused_field


@dataclass(frozen=True)
class EmbeddingModelEntry:
    """One model a provider serves, and the width it answers at."""

    model: str
    dim: int


@dataclass(frozen=True)
class EmbeddingProviderEntry:
    """One provider that can embed, as the catalog file states it."""

    provider: str
    name: str
    # The OpenAI-compatible root the `/embeddings` call is made against.
    base_url: str
    models: tuple[EmbeddingModelEntry, ...]
    # Whether this deployment's own `OPENROUTER_API_KEY` belongs to this provider.
    # Exactly one entry may set it, and it is what a collection with no key of its
    # own falls back to - sending that key anywhere else would be handing one
    # vendor's credential to another.
    deployment_key: bool = False

    def serves(self, model: str, dim: int) -> bool:
        """Whether this provider answers for `model` at exactly `dim`."""
        return any(entry.model == model and entry.dim == dim for entry in self.models)


CATALOG: tuple[EmbeddingProviderEntry, ...] = catalog.load(
    "embedding_providers.json", TypeAdapter(tuple[EmbeddingProviderEntry, ...])
)


def providers() -> tuple[EmbeddingProviderEntry, ...]:
    """Every provider a collection may embed through, in catalog order."""
    return CATALOG


def get(provider: str) -> EmbeddingProviderEntry | None:
    """One provider, or None for an id this deployment does not offer."""
    return next((entry for entry in CATALOG if entry.provider == provider), None)


def deployment_provider() -> EmbeddingProviderEntry:
    """The provider the deployment's own key belongs to.

    The catalog is validated to hold exactly one, at import, by
    `tests/test_embedding_providers.py`: a fallback key with no address to send it
    to, or two addresses claiming it, is a deployment that cannot embed and finds
    out one document at a time.
    """
    return next(entry for entry in CATALOG if entry.deployment_key)


def require(provider: str | None, *, model: str, dim: int) -> EmbeddingProviderEntry:
    """The provider to record, refused if it cannot serve this model at this width.

    `None` is the deployment's own provider, which is what a collection created
    before providers were a choice has.

    Raises:
        BadRequestError: If the id is not one this deployment offers, or the
            provider does not serve `model` at `dim` - both named on the
            `embedding_provider` field, because that is the control that was
            wrong.
    """
    if provider is None:
        return deployment_provider()
    entry = get(provider)
    if entry is None:
        offered = ", ".join(item.provider for item in CATALOG)
        raise refused_field(
            "embedding_provider",
            f"'{provider}' is not an embedding provider this build offers. Choose one of: {offered}.",
        )
    if not entry.serves(model, dim):
        raise refused_field(
            "embedding_provider",
            f"{entry.name} does not serve '{model}' at {dim} dimensions, and a collection's "
            "model and width are fixed by the vectors already in it.",
            model=model,
            dim=dim,
        )
    return entry
