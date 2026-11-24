"""Shared image execution never retries an uncertain workflow submission."""

import base64
import json
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from pydantic_ai.exceptions import ModelUnavailableError, UnexpectedModelBehavior, UserError
from pydantic_ai.messages import BinaryContent, BinaryImage
from pydantic_ai.models.openai import OpenAIResponsesModelSettings
from pydantic_ai.native_tools import ImageGenerationTool
from pydantic_ai.settings import ModelSettings

from app.services import image_generation as images

pytestmark = pytest.mark.anyio

IMAGE = b"synthetic-image-bytes"


def response(*, image=True):
    content = (
        [
            {
                "id": "ig_test",
                "type": "image_generation_call",
                "status": "completed",
                "result": base64.b64encode(IMAGE).decode(),
            }
        ]
        if image
        else [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "No image", "annotations": []}],
            }
        ]
    )
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "gpt-5.4",
        "status": "completed",
        "output": content,
        "usage": {"input_tokens": 7, "output_tokens": 1, "total_tokens": 8},
    }


def openai_transport(monkeypatch, handler):
    clients = []
    real = images.ImageHTTPClient

    def build(**kwargs):
        transport = real(**kwargs, transport=httpx2.MockTransport(handler))
        clients.append(transport)
        return transport

    monkeypatch.setattr(images, "ImageHTTPClient", build)
    return clients


@pytest.mark.security
@pytest.mark.parametrize("reference", [False, True])
async def test_one_image_request_uses_the_fixed_endpoint_and_authorized_reference(
    monkeypatch, reference
):
    requests = []

    def answer(request):
        requests.append(request)
        return httpx2.Response(200, json=response())

    clients = openai_transport(monkeypatch, answer)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid/")
    supplied = BinaryContent(data=b"reference", media_type="image/png") if reference else None
    async with images.open_image_model("openai-responses:gpt-5.4", "test-key") as model:
        result = await images.generate_image(
            model,
            prompt="A synthetic sample",
            tool=ImageGenerationTool(model="gpt-image-2"),
            reference_image=supplied,
            instrument=False,
            model_settings=ModelSettings(max_tokens=4096),
        )
    assert isinstance(result, BinaryImage) and result.data == IMAGE
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST" and str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["tools"][0]["type"] == "image_generation"
    assert body["tools"][0]["model"] == "gpt-image-2"
    assert body["max_output_tokens"] == 4096 and body["max_tool_calls"] == 1
    assert body["service_tier"] == "default"
    references = [
        content
        for item in body["input"]
        if item.get("role") == "user" and isinstance(item["content"], list)
        for content in item["content"]
        if content["type"] == "input_image"
    ]
    assert len(references) == int(reference)
    if reference:
        assert references[0]["image_url"] == "data:image/png;base64,cmVmZXJlbmNl"
    assert clients[0].is_closed


@pytest.mark.security
@pytest.mark.parametrize(
    "single_request,requested,expected",
    [
        (True, None, "default"),
        (True, "priority", "default"),
        (False, None, None),
        (False, "priority", "priority"),
    ],
)
async def test_workflow_pins_standard_pricing_while_agent_requests_keep_their_tier(
    monkeypatch, single_request, requested, expected
):
    requests = []

    def answer(request):
        requests.append(request)
        return httpx2.Response(200, json=response())

    clients = openai_transport(monkeypatch, answer)
    supplied = OpenAIResponsesModelSettings(max_tokens=4096)
    if requested is not None:
        supplied["openai_service_tier"] = requested
    original = dict(supplied)
    # Both cases own this synthetic transport; generate_image alone decides
    # whether workflow request restrictions apply to the shared SDK call.
    async with images.open_image_model("openai-responses:gpt-5.4", "test-key") as model:
        result = await images.generate_image(
            model,
            prompt="A synthetic sample",
            tool=ImageGenerationTool(model="gpt-image-1.5"),
            instrument=False,
            model_settings=supplied,
            single_request=single_request,
        )
    assert result.data == IMAGE and len(requests) == 1
    body = json.loads(requests[0].content)
    assert body.get("service_tier") == expected
    assert ("service_tier" in body) is (expected is not None)
    assert body.get("max_tool_calls") == (1 if single_request else None)
    assert supplied == original and clients[0].is_closed


@pytest.mark.parametrize("failure", ["server", "missing_image"])
async def test_provider_failure_or_invalid_output_never_submits_a_second_paid_request(
    monkeypatch, failure
):
    requests = []

    def answer(request):
        requests.append(request)
        return (
            httpx2.Response(503, json={"error": {"message": "synthetic unavailable"}})
            if failure == "server"
            else httpx2.Response(200, json=response(image=False))
        )

    clients = openai_transport(monkeypatch, answer)
    error = ModelUnavailableError if failure == "server" else UnexpectedModelBehavior
    with pytest.raises(error):
        async with images.open_image_model("openai-responses:gpt-5.4", "test-key") as model:
            await images.generate_image(
                model,
                prompt="Sample",
                tool=ImageGenerationTool(),
                instrument=False,
                model_settings=ModelSettings(max_retries=3),
            )
    assert len(requests) == 1
    assert clients[0].is_closed


@pytest.mark.parametrize("unavailable", [False, True])
async def test_google_transport_attempts_once_and_closes_both_owned_client_surfaces(
    monkeypatch, unavailable
):
    requests = []
    created = []
    real = images.GoogleClient

    def answer(request):
        requests.append(request)
        if not unavailable:
            return httpx2.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": base64.b64encode(IMAGE).decode(),
                                        }
                                    }
                                ],
                            },
                            "finishReason": "STOP",
                            "index": 0,
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 7,
                        "candidatesTokenCount": 1,
                        "totalTokenCount": 8,
                    },
                    "modelVersion": "gemini-3-pro-image",
                },
            )
        return httpx2.Response(
            503,
            json={
                "error": {"code": 503, "message": "synthetic unavailable", "status": "UNAVAILABLE"}
            },
        )

    def build(**kwargs):
        options = kwargs["http_options"]
        assert options.retry_options.attempts == 1
        assert options.base_url == "https://generativelanguage.googleapis.com"
        assert kwargs["vertexai"] is False
        client = real(**kwargs)
        client.close = Mock(wraps=client.close)
        client.aio.aclose = AsyncMock(wraps=client.aio.aclose)
        created.append((client, options.httpx_async_client))
        return client

    monkeypatch.setattr(images, "GoogleClient", build)
    clients = openai_transport(monkeypatch, answer)

    async def run():
        async with images.open_image_model("google:gemini-3-pro-image", "test-key") as model:
            return await images.generate_image(
                model,
                prompt="Sample",
                tool=ImageGenerationTool(),
                instrument=False,
                model_settings=ModelSettings(max_retries=3, max_tokens=4096),
            )

    if unavailable:
        with pytest.raises(ModelUnavailableError):
            await run()
    else:
        assert (await run()).data == IMAGE
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.host == "generativelanguage.googleapis.com"
    assert json.loads(requests[0].content)["generationConfig"]["maxOutputTokens"] == 4096
    client, transport = created[0]
    client.close.assert_called_once()
    client.aio.aclose.assert_awaited_once()
    assert transport is clients[0] and transport.is_closed


@pytest.mark.security
async def test_body_overrides_cannot_replace_the_request_cap_or_provider_payload(monkeypatch):
    requests = []

    def answer(request):
        requests.append(request)
        return httpx2.Response(200, json=response())

    clients = openai_transport(monkeypatch, answer)
    settings = ModelSettings(extra_body={"max_tool_calls": 5, "tools": []})
    with pytest.raises(UserError, match="cannot override"):
        async with images.open_image_model("openai-responses:gpt-5.4", "test-key") as model:
            await images.generate_image(
                model,
                prompt="Sample",
                tool=ImageGenerationTool(),
                instrument=False,
                model_settings=settings,
            )
    assert not requests and clients[0].is_closed
    assert settings == {"extra_body": {"max_tool_calls": 5, "tools": []}}


@pytest.mark.security
@pytest.mark.parametrize("model_id", ["openai-responses:gpt-5.4", "google:gemini-3-pro-image"])
async def test_paid_requests_never_follow_a_redirect_or_forward_the_key(monkeypatch, model_id):
    requests = []

    def answer(request):
        requests.append(request)
        return httpx2.Response(307, headers={"location": "https://untrusted.invalid/collect"})

    clients = openai_transport(monkeypatch, answer)
    with pytest.raises(UserError, match="redirected"):
        async with images.open_image_model(model_id, "test-key") as model:
            await images.generate_image(
                model, prompt="Sample", tool=ImageGenerationTool(), instrument=False
            )
    assert len(requests) == 1 and requests[0].url.host != "untrusted.invalid"
    assert clients[0].is_closed


@pytest.mark.parametrize("model_id", ["bare-model", "google:", "unknown:model"])
async def test_unreviewed_transport_is_refused_before_any_client_exists(monkeypatch, model_id):
    openai, google = Mock(), Mock()
    monkeypatch.setattr(images, "AsyncOpenAI", openai)
    monkeypatch.setattr(images, "GoogleClient", google)
    with pytest.raises(UserError):
        async with images.open_image_model(model_id, "test-key"):
            pytest.fail("No client should be admitted")
    openai.assert_not_called()
    google.assert_not_called()
