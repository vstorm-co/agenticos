"""Channel reference metadata must follow tool results on the provider wire."""

import json
from unittest.mock import MagicMock

import httpx2 as httpx
import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.services.channels.formatting import ChannelReference

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("completed_steps", [0, 2])
async def test_channel_metadata_keeps_parallel_results_first_after_each_resume(
    completed_steps: int,
) -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        for message in body["messages"]:
            if message["role"] != "user":
                continue
            content = message["content"]
            if not isinstance(content, list):
                continue
            returned = [i for i, block in enumerate(content) if block["type"] == "tool_result"]
            assert returned == list(range(len(returned)))
        return httpx.Response(
            200,
            json={
                "id": "msg_offline",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("Find the records")])]
    for step in range(completed_steps + 1):
        messages.extend(
            [
                ModelResponse(
                    parts=[
                        ToolCallPart("lookup", {}, tool_call_id=f"call_{step}_{i}")
                        for i in range(3)
                    ]
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart("lookup", "found", tool_call_id=f"call_{step}_{i}")
                        for i in range(3)
                    ]
                ),
            ]
        )
    original_parts = list(messages[-1].parts)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = AnthropicModel(
            "claude-sonnet-5-5",
            provider=AnthropicProvider(api_key="offline-test", http_client=client),
        )
        parameters = ModelRequestParameters()
        context = ModelRequestContext(
            model=model, messages=messages, model_settings=None, model_request_parameters=parameters
        )

        async def send(request: ModelRequestContext) -> ModelResponse:
            return await model.request(
                request.messages, {"max_tokens": 10}, request.model_request_parameters
            )

        await ChannelReference("Name: Sales", has_current_prompt=False).wrap_model_request(
            MagicMock(), request_context=context, handler=send
        )
    assert messages[-1].parts == original_parts
