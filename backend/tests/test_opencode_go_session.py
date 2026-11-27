"""OpenCode Go refuses a request without a session id (`MissingSessionID`).

Every model built for an `opencode_go` profile must carry a stable
`x-opencode-session` and an AgenticOS user agent, whoever builds it - the agent,
a reviewer, a subagent - while an operator's own `extra_headers` still win and
no other provider sends either.
"""

import json
import uuid
from dataclasses import replace
from unittest.mock import patch

import httpx
import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.models import get_user_agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider
from pydantic_ai.settings import ModelSettings

from app import __version__
from app.agents.capabilities import load_builtins
from app.agents.factory import build_agent
from app.agents.manifest import _settings as recorded_settings
from app.agents.model_resolver import (
    OPENCODE_SESSION_HEADER,
    USER_AGENT,
    ModelRequestSpec,
    ResolvedCredential,
    _OpenCodeGoProvider,
    build_model,
    provider_session,
)
from app.agents.run_reviewer import RunReviewer
from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret

pytestmark = pytest.mark.anyio

MODEL = "deepseek-v4.1-flash"


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _credential(provider: str = "opencode_go") -> ResolvedCredential:
    return ResolvedCredential(provider=provider, secret=ApiKeySecret(api_key="sk-go-test"))


def _spec(
    provider: str = "opencode_go", params: dict[str, object] | None = None
) -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="Go",
        provider=provider,
        model=MODEL,
        params=params or {},
        credential=_credential(provider),
        fallbacks=[],
    )


def _reply(request: httpx2.Request) -> httpx2.Response:
    body = {
        "id": "chat-test",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    return httpx2.Response(
        200, content=json.dumps(body), headers={"content-type": "application/json"}
    )


async def _sent(
    provider: str,
    *,
    session: str | None = None,
    settings: ModelSettings | None = None,
    runs: int = 1,
) -> list[httpx2.Request]:
    """The requests one built model sends for `runs` runs."""
    sent: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return _reply(request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as transport:
        with patch.object(OpenAICompatibleProvider, "_get_http_client", return_value=transport):
            model = build_model(_credential(provider), MODEL, session)
        agent = Agent(model, model_settings=settings)
        for _ in range(runs):
            await agent.run("hello")
    return sent


def _session_of(model: object) -> str | None:
    while isinstance(model, WrapperModel):
        model = model.wrapped
    assert isinstance(model, OpenAIChatModel)
    value = model.client.default_headers.get(OPENCODE_SESSION_HEADER)
    return value if isinstance(value, str) else None


async def test_every_go_request_carries_the_given_session_and_agenticos_user_agent() -> None:
    sent = await _sent("opencode_go", session="conversation-a", runs=2)

    assert [request.headers[OPENCODE_SESSION_HEADER] for request in sent] == [
        "conversation-a",
        "conversation-a",
    ]
    assert {request.headers["user-agent"] for request in sent} == {f"agenticos/{__version__}"}
    assert all(request.url.host == "opencode.ai" for request in sent)


async def test_without_a_session_one_model_keeps_one_and_another_gets_its_own() -> None:
    first = await _sent("opencode_go", runs=2)
    second = await _sent("opencode_go")

    ids = {request.headers[OPENCODE_SESSION_HEADER] for request in first}
    assert len(ids) == 1
    assert ids != {second[0].headers[OPENCODE_SESSION_HEADER]}


async def test_another_provider_sends_neither_header() -> None:
    sent = await _sent("kimi_code", session="conversation-a")

    assert OPENCODE_SESSION_HEADER not in sent[0].headers
    assert sent[0].headers["user-agent"] == get_user_agent()


async def test_the_operators_extra_headers_still_win() -> None:
    overridden = await _sent(
        "opencode_go",
        session="conversation-a",
        settings=ModelSettings(
            extra_headers={OPENCODE_SESSION_HEADER: "operator", "User-Agent": "my-agent/1.0"}
        ),
    )
    unrelated = await _sent(
        "opencode_go",
        session="conversation-a",
        settings=ModelSettings(extra_headers={"x-team": "a"}),
    )

    assert overridden[0].headers[OPENCODE_SESSION_HEADER] == "operator"
    assert overridden[0].headers["user-agent"] == "my-agent/1.0"
    # A header of the operator's own does not drop the product's two.
    assert unrelated[0].headers[OPENCODE_SESSION_HEADER] == "conversation-a"
    assert unrelated[0].headers["user-agent"] == USER_AGENT
    assert unrelated[0].headers["x-team"] == "a"


async def test_a_fallback_continues_the_same_session() -> None:
    sent: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        if len(sent) == 1:
            return httpx2.Response(400, content=b"{}", headers={"content-type": "application/json"})
        return _reply(request)

    spec = replace(_spec(), fallbacks=[(_credential(), "kimi-k2.6")], provider_session="s")
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as transport:
        with patch.object(OpenAICompatibleProvider, "_get_http_client", return_value=transport):
            model = spec.build()
        await Agent(model).run("hello")

    assert [request.headers[OPENCODE_SESSION_HEADER] for request in sent] == ["s", "s"]


async def test_go_refuses_a_legacy_http_client() -> None:
    async with httpx.AsyncClient() as legacy:
        with (
            patch.object(_OpenCodeGoProvider, "_get_http_client", return_value=legacy),
            pytest.raises(TypeError, match="OpenCode Go requires an httpx2 client"),
        ):
            _OpenCodeGoProvider(api_key="test", base_url="https://opencode.ai/v1", session="s")


def test_the_session_is_opaque_and_stable_per_key() -> None:
    conversation = uuid.uuid4()

    assert provider_session(conversation, "Clerk") == provider_session(conversation, "Clerk")
    assert provider_session(conversation, "Clerk") != provider_session(conversation, "Other")
    assert str(conversation) not in provider_session(conversation, "Clerk")
    assert len(provider_session(conversation, "Clerk")) == 32


class TestTheFactory:
    """The agent, its reviewers and its subagents share one rule, set in one place."""

    @staticmethod
    def _built(
        spec: AgentSpec,
        *,
        conversation_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        params: dict[str, object] | None = None,
        reviewer_models: dict[uuid.UUID, ModelRequestSpec] | None = None,
    ) -> tuple[object, list[RunReviewer], ModelSettings]:
        built = build_agent(
            spec,
            _spec(params=params),
            organization_id=uuid.uuid4(),
            conversation_id=conversation_id,
            run_id=run_id,
            reviewer_models=reviewer_models or {},
        )
        attached: list[object] = []
        built.agent.root_capability.apply(attached.append)
        settings = built.agent.model_settings
        assert isinstance(settings, dict)
        reviewers = [one for one in attached if isinstance(one, RunReviewer)]
        return built.agent.model, reviewers, settings

    def test_an_agent_keeps_one_session_across_a_conversations_runs(self) -> None:
        conversation = uuid.uuid4()
        spec = AgentSpec(name="Clerk")

        first, _, _ = self._built(spec, conversation_id=conversation, run_id=uuid.uuid4())
        second, _, _ = self._built(spec, conversation_id=conversation, run_id=uuid.uuid4())
        elsewhere, _, _ = self._built(spec, conversation_id=uuid.uuid4())
        # A subagent in the same conversation is a conversation of its own with the model.
        delegate, _, _ = self._built(AgentSpec(name="Researcher"), conversation_id=conversation)

        assert _session_of(first) == _session_of(second) == provider_session(conversation, "Clerk")
        assert _session_of(elsewhere) != _session_of(first)
        assert _session_of(delegate) == provider_session(conversation, "Researcher")

    def test_a_run_without_a_conversation_is_its_own_session(self) -> None:
        run = uuid.uuid4()

        model, _, _ = self._built(AgentSpec(name="Clerk"), run_id=run)
        anonymous, _, _ = self._built(AgentSpec(name="Clerk"))

        assert _session_of(model) == provider_session(run, "Clerk")
        assert _session_of(anonymous) is not None

    def test_a_reviewer_gets_a_session_of_its_own_in_the_conversation(self) -> None:
        conversation, profile = uuid.uuid4(), uuid.uuid4()
        spec = AgentSpec(
            name="Clerk",
            reviewers=[{"name": "sources", "model_profile_id": str(profile), "instructions": "x"}],
        )

        _, (reviewer,), _ = self._built(
            spec, conversation_id=conversation, reviewer_models={profile: _spec()}
        )
        _, (anonymous,), _ = self._built(spec, reviewer_models={profile: _spec()})

        assert _session_of(reviewer.model) == provider_session(
            conversation, "Clerk", "reviewer", "sources"
        )
        assert _session_of(anonymous.model) is not None

    def test_the_agents_settings_still_override_the_profiles_and_nothing_is_recorded(
        self,
    ) -> None:
        params: dict[str, object] = {
            "temperature": 0.9,
            "extra_headers": {OPENCODE_SESSION_HEADER: "operator"},
        }

        _, _, settings = self._built(
            AgentSpec(name="Clerk", model_settings={"temperature": 0.2}),
            conversation_id=uuid.uuid4(),
            params=params,
        )

        assert settings["temperature"] == 0.2
        assert settings.get("extra_headers") == {OPENCODE_SESSION_HEADER: "operator"}
        assert "extra_headers" not in recorded_settings(settings)
