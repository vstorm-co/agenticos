from abc import ABC, abstractmethod

from openai import OpenAI
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import record_ambient_usage
from app.core.exceptions import ConfigurationError
from app.services.rag.config import RAGSettings
from app.services.rag.models import Document


def _chunk_texts(document: Document) -> list[str]:
    return [
        doc.chunk_content if doc.chunk_content else "" for doc in (document.chunked_pages or [])
    ]


class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        pass

    @abstractmethod
    def embed_document(self, document: Document) -> list[list[float]]:
        pass

    @abstractmethod
    def warmup(self) -> None:
        """Ensures the model is loaded and ready for inference."""


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding provider using the OpenAI API.

    Uses OpenAI's embedding models to generate text embeddings.
    """

    def __init__(
        self,
        model: str,
        api_key: str = "",
        base_url: str | None = None,
        key_origin: str | None = None,
    ) -> None:
        """Initialize the OpenAI embedding provider.

        Args:
            model: The OpenAI embedding model name (e.g., 'text-embedding-3-small').
            api_key: API key for `base_url`. Absent, embedding is unavailable.
            base_url: Override base URL (e.g. OpenRouter-compatible endpoint).
            key_origin: Where `api_key` came from, said in words, for the
                refusal below. A per-collection caller passes what
                `ResolvedEmbeddings.describe` built; a caller with no collection
                in hand passes nothing, and has no key either.
        """
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._key_origin = key_origin
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        """The API client, built on first use rather than in `__init__`.

        Constructing it eagerly made every RAG dependency a credential check,
        including for the half of RAG that never embeds anything: reading a
        collection's stats is one `SELECT COUNT(*)`, and on a deployment with
        no key it answered 500 with an OpenAI SDK traceback, because the client
        was built while FastAPI was still resolving dependencies.

        The key is required rather than left to the SDK's `OPENAI_API_KEY`
        fallback. That fallback could not work here - `base_url` is the
        collection's provider, so an OpenAI key would have been accepted at
        construction and rejected on the first request - and silently sending
        one vendor's credential to another is not a fallback worth keeping.

        The advice depends on who is asking. A collection has a `key_origin`
        naming it and the key it tried, and what it needs is a usable key of its
        own from its organization's vault. A caller with no collection - the
        warmup, a `rag-*` command embedding outside any collection - has no key
        to try, because there is no deployment-wide embedding credential: the
        refusal says so rather than advising a variable that does not exist.
        """
        if self._client is None:
            if not self._api_key:
                details: dict[str, str] = {
                    "model": self.model,
                    "endpoint": self._base_url or "the provider's default",
                }
                if self._key_origin is None:
                    raise ConfigurationError(
                        message=(
                            "No embedding credential applies to this call: it embeds outside "
                            "any collection, and every embedding key belongs to a collection. "
                            "Embed through a knowledge base that names a vault key."
                        ),
                        details={**details, "key_origin": "none"},
                    )
                raise ConfigurationError(
                    message=(
                        f"No embedding credential is configured for {self._key_origin}, so "
                        "documents cannot be indexed or searched. Give the collection a key "
                        "for that provider from its organization's vault."
                    ),
                    details={**details, "key_origin": self._key_origin},
                )
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model, input=texts)
        # Embedding tokens are spend like any other: booked to whichever run or
        # ingestion job is metering, priced by the same lookup as chat models.
        # This used to be dropped on the floor, which made every knowledge
        # search and every document indexed invisible to the monthly budgets.
        # The "openai" hint is what resolves the price - `genai-prices` cannot
        # auto-detect embedding model names - and a model the hint does not
        # match is retried without it rather than mispriced.
        if response.usage is not None:
            record_ambient_usage(
                self.model,
                RequestUsage(input_tokens=response.usage.prompt_tokens),
                provider="openai",
            )
        return [data.embedding for data in response.data]

    def embed_document(self, document: Document) -> list[list[float]]:
        return self.embed_queries(_chunk_texts(document))

    def warmup(self) -> None:
        pass


class EmbeddingService:
    def __init__(
        self,
        settings: RAGSettings,
        api_key: str | None = None,
        expected_dim: int | None = None,
        key_origin: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """One model, one endpoint, one credential, one expected width.

        `api_key` is the collection's vault key, passed by the per-collection
        caller (see `embedding_resolution`); there is no deployment-wide key to
        default to, so a service built without one refuses on first use.
        `expected_dim` defaults to the config's derived width; a collection
        passes the width its table was actually created at, which a later
        catalog change must not overrule. `key_origin` says in words where
        `api_key` came from, so a refusal for an empty one is actionable.

        `base_url` is the collection's provider. It used to be this class's one
        hardcoded string, so every collection embedded through OpenRouter
        whatever key it had chosen: an organization's OpenAI key was sent to
        openrouter.ai, and refused there. A service with no collection has no
        endpoint either, which the empty key turns into a refusal before any
        request is built.
        """
        config = settings.embeddings_config
        self.expected_dim = expected_dim if expected_dim is not None else config.dim
        self.provider = OpenAIEmbeddingProvider(
            model=config.model,
            api_key=api_key or "",
            base_url=base_url,
            key_origin=key_origin,
        )

    def embed_query(self, query: str) -> list[float]:
        result = self.provider.embed_queries([query])[0]
        if len(result) != self.expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.expected_dim}, "
                f"got {len(result)}. Check your embedding model configuration."
            )
        return result

    def embed_document(self, document: Document) -> list[list[float]]:
        results = self.provider.embed_document(document)
        if results and len(results[0]) != self.expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.expected_dim}, "
                f"got {len(results[0])}. Check your embedding model configuration."
            )
        return results

    def warmup(self) -> None:
        self.provider.warmup()
