"""A real Pydantic AI tool cycle crosses the private inference HTTP contract."""

import json
from base64 import b64decode
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.capabilities import Instrumentation, Thinking
from pydantic_ai.tools import ToolReturn

from app.agents.claude_subscription import ClaudeSubscriptionModelClient
from app.agents.ephemeral_media import ephemeral_image
from app.core.claude_subscription import ClaudeSubscriptionOwner
from app.core.config import settings
from app.services.claude_subscription import ClaudeSubscriptionRuntime

pytestmark = pytest.mark.anyio


async def test_tool_reply_and_screenshot_cross_native_inference_http(monkeypatch):
    owner = ClaudeSubscriptionOwner(uuid4(), uuid4())
    service_key = "test-runtime-key-with-no-provider-credentials"
    monkeypatch.setattr(settings, "CLAUDE_SUBSCRIPTION_URL", "http://native-runtime:8080")
    monkeypatch.setattr(settings, "CLAUDE_SUBSCRIPTION_SERVICE_KEY", SecretStr(service_key))
    requests = []

    def respond(request):
        assert request.method == "POST"
        assert request.url.path == "/v1/infer"
        assert request.headers["X-Claude-Runtime-Key"] == service_key
        body = json.loads(request.content)
        assert body["organization_id"] == str(owner.organization_id)
        assert body["user_id"] == str(owner.user_id)
        assert body["model"] == "opus"
        requests.append(body)
        prompt = body["prompt"]
        request_data = json.loads(prompt[prompt.index('{"instructions"') :])
        if len(requests) == 1:
            assert "images" not in body
            assert any(
                tool["name"] == "computer_screenshot" for tool in request_data["available_tools"]
            )
            decision = {
                "text": None,
                "tool_calls": [{"name": "computer_screenshot", "arguments_json": "{}"}],
            }
        else:
            assert body["thinking"] == "medium"
            assert b64decode(body["images"][0]["data"], validate=True) == screenshot
            tool_return = next(
                part for part in request_data["conversation"] if part["role"] == "tool"
            )
            tool_call = next(
                part
                for part in request_data["conversation"]
                if part["role"] == "assistant_tool_call"
            )
            assert tool_return["call_id"] == tool_call["call_id"]
            assert tool_return["name"] == "computer_screenshot"
            assert "[image:1]" in tool_return["content"]
            decision = {"text": "I see the test desktop", "tool_calls": []}
        return httpx.Response(
            200,
            json={
                "structured_output": decision,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
                "model": "claude-opus-4-6",
            },
        )

    runtime = ClaudeSubscriptionRuntime(transport=httpx.MockTransport(respond))
    model = ClaudeSubscriptionModelClient("opus", owner=owner, runtime=runtime)
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(buffer, "JPEG")
    screenshot = buffer.getvalue()

    def computer_screenshot() -> ToolReturn:
        """Capture the managed desktop."""
        return ToolReturn(
            return_value=["Desktop 1280x800", ephemeral_image(screenshot, "image/jpeg")]
        )

    result = await Agent(
        model,
        tools=[computer_screenshot],
        capabilities=[Instrumentation(), Thinking(effort="medium")],
    ).run("Inspect the desktop")

    assert result.output == "I see the test desktop"
    assert len(requests) == 2
    assert requests[1]["thinking"] == "medium"
    assert b64decode(requests[1]["images"][0]["data"], validate=True) == screenshot
    assert requests[1]["images"][0]["media_type"] == "image/jpeg"
    assert requests[1]["prompt"]
    assert requests[1]["output_schema"]
    assert requests[1].keys() >= {
        "organization_id",
        "user_id",
        "model",
        "prompt",
        "output_schema",
        "images",
        "thinking",
    }
