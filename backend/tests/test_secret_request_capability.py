"""The `secret_request` capability through a real agent run (#13).

The mechanism a run parked on a secret rests on: the surface raises
`CallDeferred`, the run ends waiting on the call, and the safe
acknowledgement - name and hint, never the value - is handed back as that
call's result, which the model reads as if answered live.
"""

import json

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

from app.agents.capabilities._registry import CapabilityBinding, build, load_builtins
from app.agents.capabilities.secret_request import SECRET_REQUEST_CAPABILITY_ID
from app.agents.deps import AgentDeps
from app.agents.secret_request import SECRET_REQUEST_TOOL, secret_request_result
from app.services.agent_runner import PausedRunState, _classify_output

pytestmark = pytest.mark.anyio

SENTINEL = "sk-test-SENTINEL-VALUE-7f3a9c"


def _asks_then_reports(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    returns = [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]
    if not returns:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    SECRET_REQUEST_TOOL,
                    {
                        "secret_name": "acme_api_key",
                        "what_for": "Acme CRM, to list contacts",
                    },
                    tool_call_id="secret-1",
                )
            ]
        )
    return ModelResponse(parts=[TextPart(json.dumps(str(returns[0].content)))])


def _agent() -> Agent[AgentDeps, str | DeferredToolRequests]:
    load_builtins()
    capabilities = build([CapabilityBinding(capability_id=SECRET_REQUEST_CAPABILITY_ID)])
    return Agent(
        FunctionModel(_asks_then_reports),
        deps_type=AgentDeps,
        capabilities=capabilities,
        output_type=[str, DeferredToolRequests],
    )


@pytest.mark.security
async def test_a_secret_request_parks_the_run_waiting_on_an_answer() -> None:
    parked = await _agent().run("List my Acme contacts", deps=AgentDeps())

    assert isinstance(parked.output, DeferredToolRequests)
    [call] = parked.output.calls
    assert call.tool_name == SECRET_REQUEST_TOOL
    status, _text, _structured, state = _classify_output(parked, parked={})

    assert status.value == "awaiting_answer"
    assert state is not None
    assert state.secret_requests == ["secret-1"]
    assert state.questions == []


@pytest.mark.security
async def test_the_safe_result_continues_the_run_and_the_value_never_appears() -> None:
    parked = await _agent().run("List my Acme contacts", deps=AgentDeps())
    assert isinstance(parked.output, DeferredToolRequests)
    [call] = parked.output.calls
    _, _, _, state = _classify_output(parked, parked={})
    assert state is not None

    # The fulfil stores only this string in the parked state: name and hint.
    state.secret_results = {call.tool_call_id: secret_request_result("acme_api_key", "9c2f")}
    restored = PausedRunState.model_validate_json(state.model_dump_json())
    resumed = await _agent().run(
        message_history=ModelMessagesTypeAdapter.validate_python(restored.messages),
        deferred_tool_results=DeferredToolResults(
            calls={call.tool_call_id: restored.secret_results[call.tool_call_id]}
        ),
        deps=AgentDeps(),
    )

    assert isinstance(resumed.output, str)
    assert "acme_api_key" in resumed.output
    assert SENTINEL not in resumed.output
    assert SENTINEL not in state.model_dump_json()
    assert SENTINEL not in json.dumps(restored.model_dump(mode="json"))


@pytest.mark.security
def test_the_capability_builds_its_toolset_once() -> None:
    from app.agents.capabilities.secret_request._capability import SecretRequestCapability

    capability = SecretRequestCapability()

    assert capability.get_toolset() is capability.get_toolset()


class TestRequestSecretValidation:
    """The tool refuses a call it cannot turn into a card, before parking."""

    @pytest.fixture
    def toolset(self):
        from app.agents.capabilities.secret_request._toolset import SecretRequestToolset

        return SecretRequestToolset()

    @pytest.fixture
    def ctx(self):
        from unittest.mock import MagicMock

        return MagicMock(last_attempt=True)

    @pytest.mark.security
    async def test_an_empty_name_is_refused(self, toolset, ctx) -> None:
        result = await toolset.request_secret(ctx, "  ", "Acme CRM, to list contacts")

        assert "Name the secret to store" in result

    @pytest.mark.security
    async def test_an_overlong_name_is_refused(self, toolset, ctx) -> None:
        result = await toolset.request_secret(ctx, "k" * 129, "Acme CRM, to list contacts")

        assert "under 128 characters" in result

    @pytest.mark.security
    async def test_a_missing_reason_is_refused(self, toolset, ctx) -> None:
        result = await toolset.request_secret(ctx, "acme_api_key", "  ")

        assert "Say what the secret is for" in result

    @pytest.mark.security
    async def test_an_overlong_reason_is_refused(self, toolset, ctx) -> None:
        result = await toolset.request_secret(ctx, "acme_api_key", "w" * 1001)

        assert "under 1000 characters" in result

    @pytest.mark.security
    async def test_an_unknown_kind_is_refused_before_parking(self, toolset, ctx) -> None:
        from unittest.mock import AsyncMock, patch

        with patch(
            "app.agents.capabilities.secret_request._toolset.park_the_secret_request",
            AsyncMock(),
        ) as park:
            result = await toolset.request_secret(
                ctx, "acme_api_key", "Acme CRM", kind="not_a_secret_kind"
            )
            none_result = await toolset.request_secret(ctx, "acme_api_key", "Acme CRM", kind="none")

        assert "supported secret kinds" in result
        assert "api_key" in result
        assert "none" not in result
        assert "supported secret kinds" in none_result
        park.assert_not_awaited()

    @pytest.mark.security
    async def test_a_kind_over_32_characters_is_refused_before_parking(self, toolset, ctx) -> None:
        from unittest.mock import AsyncMock, patch

        with patch(
            "app.agents.capabilities.secret_request._toolset.park_the_secret_request",
            AsyncMock(),
        ) as park:
            result = await toolset.request_secret(ctx, "acme_api_key", "Acme CRM", kind="k" * 33)

        assert "supported secret kinds" in result
        park.assert_not_awaited()

    @pytest.mark.security
    async def test_a_valid_call_that_somehow_does_not_park_still_answers(
        self, toolset, ctx
    ) -> None:
        from unittest.mock import AsyncMock, patch

        with patch(
            "app.agents.capabilities.secret_request._toolset.park_the_secret_request",
            AsyncMock(),
        ):
            result = await toolset.request_secret(ctx, "acme_api_key", "Acme CRM")

        assert result == "Waiting for the person to provide the secret."
