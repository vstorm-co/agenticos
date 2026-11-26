"""Custom endpoint responses are validated before indexing, querying or passing a probe."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
from openai import OpenAI
from openai.types import CreateEmbeddingResponse, Embedding, create_embedding_response

from app.agents.capabilities.budget import SpendLedger, metered_by
from app.core.exceptions import ExternalServiceError
from app.services.rag.config import RAGSettings
from app.services.rag.embeddings import EmbeddingService, OpenAIEmbeddingProvider
from tests.embedding_responses import embedding_response


def _provider(vectors: list[object]) -> OpenAIEmbeddingProvider:
    provider = OpenAIEmbeddingProvider(model="custom", api_key="private")
    provider._client = MagicMock(
        embeddings=MagicMock(
            with_raw_response=MagicMock(
                create=MagicMock(return_value=embedding_response(vectors, prompt_tokens=7))
            )
        )
    )
    return provider


@pytest.mark.parametrize(
    "vector",
    [
        ["not-numeric"],
        [None],
        [True],
        [float("nan")],
        [float("inf")],
        [1e308],
        [-1e308],
        [],
        [[1.0]],
    ],
)
def test_actual_provider_refuses_invalid_vectors_and_retains_billed_usage(
    vector: list[object],
) -> None:
    ledger = SpendLedger()
    with metered_by(ledger), pytest.raises(ExternalServiceError, match="invalid vectors"):
        _provider([vector]).embed_queries(["query"])
    assert sum(entry.input_tokens for entry in ledger.entries) == 7


@pytest.mark.parametrize("vectors", [[], [[1.0], [2.0]]])
def test_actual_provider_refuses_short_or_extra_response(vectors: list[object]) -> None:
    with pytest.raises(ExternalServiceError, match="wrong number"):
        _provider(vectors).embed_queries(["query"])


def test_provider_validates_actual_openai_sdk_response_without_coercing_strings() -> None:
    response = CreateEmbeddingResponse(
        object="list",
        model="custom",
        usage=create_embedding_response.Usage(prompt_tokens=1, total_tokens=1),
        data=[Embedding(object="embedding", index=0, embedding=[1.0, 2.0])],
    )
    provider = _provider([])
    provider._client.embeddings.with_raw_response.create.return_value = MagicMock(
        http_response=MagicMock(content=response.model_dump_json().encode())
    )
    vectors = provider.embed_queries(["query"])
    assert vectors == [[1.0, 2.0]]


@pytest.mark.parametrize("method", ["embed_queries", "embed_document"])
def test_service_checks_every_vector_width_before_database_use(method: str) -> None:
    service = EmbeddingService(RAGSettings(), expected_dim=2)
    service.provider = MagicMock()
    getattr(service.provider, method).return_value = [[1.0, 2.0], [3.0]]
    with pytest.raises(ValueError, match="dimension mismatch"):
        getattr(service, method)(MagicMock())


@pytest.mark.parametrize(
    "vector",
    [
        ["not-numeric"],
        [None],
        [True],
        [float("nan")],
        [float("inf")],
        [1e308],
        [-1e308],
        pytest.param([70000.0] * 2001, id="wide-halfvec-overflow"),
    ],
)
def test_actual_sdk_http_response_is_refused_before_returning_invalid_vectors(
    vector: list[object],
) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "object": "list",
                    "model": "custom",
                    "data": [{"object": "embedding", "index": 0, "embedding": vector}],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                }
            ),
            headers={"content-type": "application/json"},
        )

    provider = OpenAIEmbeddingProvider(model="custom", api_key="fixture-key")
    with (
        httpx.Client(transport=httpx.MockTransport(answer)) as transport,
        OpenAI(
            api_key="fixture-key", base_url="https://gateway.example/v1", http_client=transport
        ) as client,
    ):
        provider._client = client
        with pytest.raises(ExternalServiceError, match="invalid vectors"):
            provider.embed_queries(["query"])


@pytest.mark.parametrize(
    "content", [b"not json", b"null", b"[]", b'{"data":null}', b'{"data":[{"embedding":[true]}]}']
)
def test_actual_sdk_malformed_wire_body_is_a_controlled_provider_error(content: bytes) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, headers={"content-type": "application/json"})

    provider = OpenAIEmbeddingProvider(model="custom", api_key="fixture-key")
    with (
        httpx.Client(transport=httpx.MockTransport(answer)) as transport,
        OpenAI(
            api_key="fixture-key", base_url="https://gateway.example/v1", http_client=transport
        ) as client,
    ):
        provider._client = client
        with pytest.raises(ExternalServiceError):
            provider.embed_queries(["query"])


@pytest.mark.anyio
async def test_async_probe_refuses_raw_boolean_and_closes_the_actual_sdk_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openai import AsyncOpenAI

    from app.services.rag import embeddings

    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [True]}]})

    client = AsyncOpenAI(
        api_key="fixture-key",
        base_url="https://gateway.example/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)),
        max_retries=0,
    )

    def build(**options: object) -> AsyncOpenAI:
        return client

    monkeypatch.setattr(embeddings, "AsyncOpenAI", build)
    with pytest.raises(embeddings.EmbeddingProbeError) as refused:
        await embeddings.embed_for_probe(
            base_url="https://gateway.example/v1",
            api_key="fixture-key",
            keyless=False,
            model="custom",
            text="query",
        )
    assert refused.value.outcome == "model_unknown"
    assert client.is_closed()
    assert len(requests) == 1
    assert json.loads(requests[0].content)["encoding_format"] == "float"


@pytest.mark.anyio
async def test_paid_raw_response_is_recorded_before_sdk_close_and_vector_refusal(monkeypatch):
    from openai import AsyncOpenAI

    from app.agents.capabilities.budget import SpendLedger, metered_by
    from app.services.rag import embeddings

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"embedding": [True]}], "usage": {"prompt_tokens": 8}}
        )

    client = AsyncOpenAI(
        api_key="fixture-key",
        base_url="https://gateway.example/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)),
        max_retries=0,
    )
    ledger = SpendLedger()
    close = client.close

    async def checked_close():
        assert ledger.input_tokens == 8
        assert ledger.total_usd > 0
        await close()

    monkeypatch.setattr(client, "close", checked_close)
    monkeypatch.setattr(embeddings, "AsyncOpenAI", lambda **_: client)
    with metered_by(ledger), pytest.raises(embeddings.EmbeddingProbeError):
        await embeddings.embed_for_probe(
            base_url="https://gateway.example/v1",
            api_key="fixture-key",
            keyless=False,
            model="text-embedding-3-small",
            text="query",
        )
    assert client.is_closed()
    assert len(ledger.entries) == 1


@pytest.mark.parametrize(
    "dim,component,allowed",
    [(2000, 70000.0, True), (2001, 65504.0, True), (2001, 70000.0, False), (2001, -70000.0, False)],
)
def test_provider_respects_actual_index_precision(dim, component, allowed):
    ledger = SpendLedger()
    with metered_by(ledger):
        if allowed:
            assert len(_provider([[component] * dim]).embed_queries(["query"])[0]) == dim
        else:
            with pytest.raises(ExternalServiceError, match="half-precision index"):
                _provider([[component] * dim]).embed_queries(["query"])
    assert ledger.input_tokens == 7
