"""One real agent step crosses the private HTTP protocol and reaches native stdin."""

import importlib.util
import json
import sys
from base64 import b64decode
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
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


@pytest.fixture
def native_modules(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "integrations" / "claude-subscription"
    modules = {}
    for name in ("isolation", "schemas", "runtime", "server"):
        spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    return modules


async def test_computer_screenshot_and_thinking_cross_agent_http_and_native_stdin(
    native_modules, monkeypatch, tmp_path
):
    isolation = native_modules["isolation"]
    schema = native_modules["schemas"]
    native = native_modules["runtime"]
    server = native_modules["server"]
    owner = ClaudeSubscriptionOwner(uuid4(), uuid4())
    native_owner = isolation.Owner(owner.organization_id, owner.user_id)
    homes = MagicMock(spec=isolation.Homes)
    home = isolation.Home(tmp_path, 20001)
    homes.get.return_value = home
    engine = native.ClaudeRuntime(homes, cli_path="/test-only-not-executed")
    connected = schema.ConnectionStatus(connected=True, state="connected")
    engine.status = AsyncMock(return_value=connected)
    engine.account(native_owner).status = connected
    native_calls = []

    async def command(actual_home, arguments, **kwargs):
        assert actual_home is home
        native_calls.append((arguments, kwargs))
        decision = (
            {"text": None, "tool_calls": [{"name": "computer_screenshot", "arguments_json": "{}"}]}
            if len(native_calls) == 1
            else {"text": "I see the test desktop", "tool_calls": []}
        )
        result = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": decision,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        output = json.dumps(result)
        if len(native_calls) == 2:
            output = json.dumps({"type": "system", "subtype": "init"}) + "\n" + output + "\n"
        return output.encode(), 0

    engine.command = command
    service_key = "test-runtime-key-with-no-provider-credentials"
    monkeypatch.setattr(settings, "CLAUDE_SUBSCRIPTION_URL", "http://native-runtime:8080")
    monkeypatch.setattr(settings, "CLAUDE_SUBSCRIPTION_SERVICE_KEY", SecretStr(service_key))
    app = server.create_app(engine, service_key)
    requests = []
    asgi = httpx.ASGITransport(app)

    class RecordingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            requests.append(json.loads(request.content))
            assert request.headers["X-Claude-Runtime-Key"] == service_key
            return await asgi.handle_async_request(request)

    client = ClaudeSubscriptionRuntime(transport=RecordingTransport())
    model = ClaudeSubscriptionModelClient("opus", owner=owner, runtime=client)
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
    assert len(requests) == len(native_calls) == 2
    assert "images" not in requests[0]
    assert requests[1]["thinking"] == "medium"
    assert requests[1]["organization_id"] == str(owner.organization_id)
    assert requests[1]["user_id"] == str(owner.user_id)
    assert b64decode(requests[1]["images"][0]["data"], validate=True) == screenshot
    arguments, invocation = native_calls[1]
    for option, value in [
        ("--tools", ""),
        ("--mcp-config", '{"mcpServers":{}}'),
        ("--permission-mode", "dontAsk"),
        ("--max-turns", "3"),
        ("--input-format", "stream-json"),
        ("--output-format", "stream-json"),
        ("--effort", "medium"),
    ]:
        assert arguments[arguments.index(option) + 1] == value
    assert {
        "--safe-mode",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--no-chrome",
        "--verbose",
    } <= set(arguments)
    assert json.loads(arguments[arguments.index("--settings") + 1]) == {
        "alwaysThinkingEnabled": True
    }
    [line] = invocation["payload"].splitlines()
    event = json.loads(line)
    assert event["type"] == "user" and event["message"]["role"] == "user"
    content = event["message"]["content"]
    assert content[1] == {"type": "text", "text": "[image:1]"}
    assert content[2]["type"] == "image"
    assert content[2]["source"]["type"] == "base64"
    assert content[2]["source"]["media_type"] == "image/jpeg"
    assert b64decode(content[2]["source"]["data"], validate=True) == screenshot
    prompt = content[0]["text"]
    history = json.loads(prompt[prompt.index('{"instructions"') :])["conversation"]
    returned = next(part for part in history if part["role"] == "tool")
    called = next(part for part in history if part["role"] == "assistant_tool_call")
    assert returned["call_id"] == called["call_id"]
    assert returned["name"] == "computer_screenshot" and "[image:1]" in returned["content"]
    assert invocation["timeout"] == 600 and invocation["output_limit"] == 4 * 1024 * 1024
    assert invocation["max_output_tokens"] == 8192
    assert not engine.active and not engine.processes
