"""Recorded tool visibility agrees with the provider payload after discovery."""

import json
from dataclasses import replace

import httpx
import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition

from app.agents.manifest import RecordingModel, RunRecorder, as_payload

pytestmark = pytest.mark.anyio


async def test_recording_distinguishes_the_catalog_from_schemas_sent_to_the_provider() -> None:
    wire_tools: list[list[str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        wire_tools.append([tool["function"]["name"] for tool in body.get("tools", [])])
        return httpx.Response(
            200,
            json={
                "id": "chat-test",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4.1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
            },
        )

    recorder = RunRecorder()
    parameters = ModelRequestParameters(
        function_tools=[
            ToolDefinition(name="read_file"),
            ToolDefinition(name="notion_fetch", defer_loading=True, with_native="tool_search"),
            ToolDefinition(name="search_tools", unless_native="tool_search"),
        ],
    )
    messages = [ModelRequest(parts=[UserPromptPart(content="Read the source")])]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = OpenAIProvider(api_key="test-key", http_client=client)
        model = RecordingModel(OpenAIChatModel("gpt-4.1", provider=provider), recorder)
        await model.request(messages, None, parameters)
        await model.request(
            messages, None, replace(parameters, revealed_tool_names={"notion_fetch"})
        )

    payload = as_payload(recorder)
    assert "notion_fetch" not in wire_tools[0] and "notion_fetch" in wire_tools[1]
    for request, tools in zip(payload["requests"], wire_tools, strict=True):
        assert request["tool_counts"]["visible"] == len(tools)
        assert request["visible_tool_names"] == tools
    assert payload["requests"][0]["tool_counts"]["withheld"] == 1
    assert payload["requests"][1]["tool_counts"]["withheld"] == 0
    assert {tool["name"]: tool["visibility"] for tool in payload["tools"]}[
        "notion_fetch"
    ] == "visible"
    assert parameters.tool_visibility is None and parameters.function_tools[1].defer_loading
