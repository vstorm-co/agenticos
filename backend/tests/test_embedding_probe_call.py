"""The one request a test makes, and how an endpoint's answer becomes an outcome.

The SDK's exception text can quote the address and the response body, and a test's
result goes to a browser; so the outcome is chosen by class and the text is dropped.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.services.rag import embeddings
from app.services.rag.embeddings import EmbeddingProbeError, embed_for_probe

pytestmark = pytest.mark.anyio

_URL = "https://gateway.internal.example/v1?token=hunter2"
_KEY = "sk-very-secret"


def _response(status: int) -> MagicMock:
    return MagicMock(status_code=status, headers={}, request=MagicMock())


def _status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    return cls(f"{_URL} said {_KEY}", response=_response(status), body=None)


def _client(*, answer: object = None, error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    client.embeddings.create = AsyncMock(return_value=answer, side_effect=error)
    client.close = AsyncMock()
    return client


async def _embed(client: MagicMock, **overrides: object) -> list[float]:
    arguments = {
        "base_url": _URL,
        "api_key": _KEY,
        "keyless": False,
        "model": "m",
        "text": "hello",
    } | overrides
    with patch.object(embeddings, "AsyncOpenAI", return_value=client) as built:
        try:
            return await embed_for_probe(**arguments)  # type: ignore[arg-type]
        finally:
            _embed.built = built  # type: ignore[attr-defined]


def _answer(*vectors: object) -> MagicMock:
    return MagicMock(data=[MagicMock(embedding=vector) for vector in vectors])


async def test_one_request_is_made_with_no_sdk_retry_and_the_client_is_closed() -> None:
    client = _client(answer=_answer([1, 2.5]))

    vector = await _embed(client)

    assert vector == [1.0, 2.5]
    client.embeddings.create.assert_awaited_once_with(model="m", input=["hello"])
    client.close.assert_awaited_once()
    options = _embed.built.call_args.kwargs  # type: ignore[attr-defined]
    assert options["max_retries"] == 0
    assert options["timeout"] == embeddings.PROBE_TIMEOUT_SECONDS
    assert options["api_key"] == _KEY


async def test_a_keyless_endpoint_is_sent_the_placeholder_not_a_key() -> None:
    await _embed(_client(answer=_answer([1.0])), keyless=True, api_key="")

    assert _embed.built.call_args.kwargs["api_key"] == "keyless"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (_status_error(openai.AuthenticationError, 401), "key_refused"),
        (_status_error(openai.PermissionDeniedError, 403), "key_refused"),
        (_status_error(openai.NotFoundError, 404), "model_unknown"),
        (_status_error(openai.BadRequestError, 400), "model_unknown"),
        (_status_error(openai.UnprocessableEntityError, 422), "model_unknown"),
        (_status_error(openai.InternalServerError, 502), "unreachable"),
        (_status_error(openai.RateLimitError, 429), "unreachable"),
        (_status_error(openai.ConflictError, 409), "unreachable"),
        (openai.APIConnectionError(request=MagicMock()), "unreachable"),
        (openai.APITimeoutError(request=MagicMock()), "unreachable"),
        (openai.APIResponseValidationError(_response(200), body="<html>"), "model_unknown"),
    ],
)
async def test_a_failure_is_an_outcome_by_class_and_the_message_holds_nothing_of_the_call(
    error: Exception, outcome: str
) -> None:
    client = _client(error=error)

    with pytest.raises(EmbeddingProbeError) as failed:
        await _embed(client)

    assert failed.value.outcome == outcome
    assert failed.value.details == {"outcome": outcome}
    for secret in (_URL, "hunter2", _KEY, "gateway.internal"):
        assert secret not in failed.value.message
    client.close.assert_awaited_once()


@pytest.mark.parametrize("answer", [MagicMock(data=[]), _answer("not-a-list"), _answer([])])
async def test_an_answer_with_no_vector_is_model_unknown(answer: MagicMock) -> None:
    with pytest.raises(EmbeddingProbeError) as failed:
        await _embed(_client(answer=answer))

    assert failed.value.outcome == "model_unknown"


async def test_only_the_exception_class_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"), pytest.raises(EmbeddingProbeError):
        await _embed(_client(error=_status_error(openai.AuthenticationError, 401)))

    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "AuthenticationError" in logged
    assert _KEY not in logged
    assert "hunter2" not in logged
