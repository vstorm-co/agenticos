"""A document's chunks are embedded in bounded requests, not one request per document.

Every chunk of a document used to go to `/embeddings` in a single call. A local
Ollama server drops the connection somewhere between 320 and 384 inputs
(`/tokenize: EOF`), and hosted APIs cap inputs per request too, so a long
manual failed to index on every attempt while a short one went through.
"""

from unittest.mock import MagicMock

from app.agents.capabilities.budget import SpendLedger, metered_by
from app.services.rag.embeddings import EMBED_BATCH_SIZE, OpenAIEmbeddingProvider

# Two full batches and a partial third: enough to catch an off-by-one at either
# boundary and a final short batch that is dropped.
TEXT_COUNT = EMBED_BATCH_SIZE * 2 + 3


def _echoing_provider() -> tuple[OpenAIEmbeddingProvider, MagicMock]:
    """A provider whose endpoint embeds `"t<n>"` as `[n]` and bills one token per input."""

    def create(*, model: str, input: list[str]) -> MagicMock:
        return MagicMock(
            data=[MagicMock(embedding=[float(text[1:])]) for text in input],
            usage=MagicMock(prompt_tokens=len(input)),
        )

    endpoint = MagicMock(side_effect=create)
    provider = OpenAIEmbeddingProvider(model="nomic-embed-text", api_key="key")
    provider._client = MagicMock(embeddings=MagicMock(create=endpoint))
    return provider, endpoint


def _texts() -> list[str]:
    return [f"t{n}" for n in range(TEXT_COUNT)]


class TestEmbeddingBatches:
    def test_no_request_carries_more_than_one_batch(self):
        provider, endpoint = _echoing_provider()

        provider.embed_queries(_texts())

        sizes = [len(call.kwargs["input"]) for call in endpoint.call_args_list]
        assert sizes == [EMBED_BATCH_SIZE, EMBED_BATCH_SIZE, 3]

    def test_vectors_come_back_in_the_order_the_texts_went_in(self):
        provider, _ = _echoing_provider()

        vectors = provider.embed_queries(_texts())

        assert vectors == [[float(n)] for n in range(TEXT_COUNT)]

    def test_every_batch_is_booked_to_the_ledger(self):
        provider, _ = _echoing_provider()
        ledger = SpendLedger()

        with metered_by(ledger):
            provider.embed_queries(_texts())

        assert sum(entry.input_tokens for entry in ledger.entries) == TEXT_COUNT
