"""Exercise the installed Otari integration through Pydantic AI and the SDK transport."""

import json
from unittest.mock import patch

import httpx2
import pytest
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai_otari import OtariProvider

from app.agents.model_resolver import PROVIDERS, ResolvedCredential, build_model
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret, NoSecret

pytestmark = [pytest.mark.anyio, pytest.mark.security]
MODEL = "anthropic:claude-sonnet-4-6"


def credential(endpoint: str | None = None) -> ResolvedCredential:
    return ResolvedCredential(
        provider="otari", secret=ApiKeySecret(api_key="otari-vault-test"), base_url=endpoint
    )


@pytest.mark.parametrize(
    "endpoint", [None, "https://eu.api.otari.ai/api/v1", "http://otari.test/api/v1"]
)
def test_otari_uses_only_the_profiles_key_and_endpoint(endpoint: str | None, monkeypatch) -> None:
    monkeypatch.setenv("OTARI_API_KEY", "wrong-ambient-otari")
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-ambient-openai")
    monkeypatch.setenv("OTARI_BASE_URL", "https://wrong-ambient.example/api/v1")
    model = build_model(credential(endpoint), MODEL)
    assert isinstance(model, OpenAIChatModel)
    assert model.system == "otari"
    assert model.client.api_key == "otari-vault-test"
    assert str(model.client.base_url) == (endpoint or "https://api.otari.ai/api/v1") + "/"
    assert model.profile["anthropic_supports_adaptive_thinking"] is True
    assert PROVIDERS["otari"].apis == ()
    assert PROVIDERS["otari"].regions == ()


def test_a_missing_otari_key_never_uses_an_environment_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-ambient-openai")
    monkeypatch.setenv("OTARI_API_KEY", "wrong-ambient-otari")
    with pytest.raises(BadRequestError, match="vault API key"):
        build_model(ResolvedCredential(provider="otari", secret=NoSecret()), MODEL)


class CountResult(BaseModel):
    count: int


@pytest.mark.parametrize("mode", ["text", "tools", "structured", "stream", "refused"])
@pytest.mark.parametrize("model_name", [MODEL, "support-agent"])
async def test_otari_serializes_real_agent_calls(mode: str, model_name: str) -> None:
    sent: list[dict[str, object]] = []
    tool_ran: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == "https://otari.test/api/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer otari-vault-test"
        payload = json.loads(request.content)
        sent.append(payload)
        assert payload["model"] == model_name
        if mode == "refused":
            return httpx2.Response(401, json={"error": {"message": "Invalid gateway key"}})
        if mode == "stream":
            assert payload["stream"] is True
            chunks = [
                {"role": "assistant", "content": "Hello"},
                {"content": " from Otari"},
                {},
            ]
            events = [
                {
                    "id": "completion",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": model_name,
                    "choices": [
                        {"index": 0, "delta": delta, "finish_reason": "stop" if i == 2 else None}
                    ],
                }
                for i, delta in enumerate(chunks)
            ]
            body = (
                "".join("data: " + json.dumps(event) + "\n\n" for event in events)
                + "data: [DONE]\n\n"
            )
            return httpx2.Response(
                200, content=body.encode(), headers={"Content-Type": "text/event-stream"}
            )
        message: dict[str, object] = {"role": "assistant", "content": "Hello from Otari"}
        finish = "stop"
        if mode == "structured" or (mode == "tools" and len(sent) == 1):
            name = payload["tools"][0]["function"]["name"]
            arguments = {"count": 7} if mode == "structured" else {"name": "Otari"}
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            }
            finish = "tool_calls"
        return httpx2.Response(
            200,
            json={
                "id": "completion",
                "object": "chat.completion",
                "created": 1,
                "model": model_name,
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        with patch.object(OtariProvider, "_get_http_client", return_value=client):
            model = build_model(credential("https://otari.test/api/v1"), model_name)
            if mode == "structured":
                result = await Agent(model, output_type=CountResult).run("Count")
                assert result.output.count == 7
            elif mode == "stream":
                async with Agent(model).run_stream("Hello") as response:
                    text = "".join([part async for part in response.stream_text(delta=True)])
                assert text == "Hello from Otari"
            elif mode == "refused":
                with pytest.raises(ModelHTTPError) as error:
                    await Agent(model).run("Hello")
                assert error.value.status_code == 401
            else:
                agent = Agent(model)
                if mode == "tools":

                    @agent.tool_plain
                    def greet(name: str) -> str:
                        tool_ran.append(name)
                        return f"Hello {name}"

                result = await agent.run("Hello")
                assert result.output == "Hello from Otari"
    assert sent
    if mode == "tools":
        assert tool_ran == ["Otari"]
        assert len(sent) == 2
