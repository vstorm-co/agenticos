from abc import ABC, abstractmethod

from openai import OpenAI
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import record_ambient_usage
from app.core.config import settings as app_settings
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

    def __init__(self, model: str, api_key: str = "", base_url: str | None = None) -> None:
        """Initialize the OpenAI embedding provider.

        Args:
            model: The OpenAI embedding model name (e.g., 'text-embedding-3-small').
            api_key: API key for `base_url`. Absent, embedding is unavailable.
            base_url: Override base URL (e.g. OpenRouter-compatible endpoint).
        """
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
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
        fallback. That fallback could not work here - `base_url` points at
        OpenRouter, so an OpenAI key would have been accepted at construction
        and rejected on the first request - and silently sending one vendor's
        credential to another is not a fallback worth keeping.
        """
        if self._client is None:
            if not self._api_key:
                raise ConfigurationError(
                    message=(
                        "No embedding credential is configured, so documents cannot be "
                        "indexed or searched. Set OPENROUTER_API_KEY in the backend "
                        "environment and restart."
                    ),
                    details={"setting": "OPENROUTER_API_KEY", "model": self.model},
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
    ) -> None:
        """One model, one credential, one expected width.

        `api_key` defaults to the deployment's key; a per-collection caller
        passes the organization's own (see `embedding_resolution`).
        `expected_dim` defaults to the config's derived width; a collection
        passes the width its table was actually created at, which a later
        catalog change must not overrule.
        """
        config = settings.embeddings_config
        self.expected_dim = expected_dim if expected_dim is not None else config.dim
        self.provider = OpenAIEmbeddingProvider(
            model=config.model,
            api_key=api_key if api_key is not None else app_settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
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
