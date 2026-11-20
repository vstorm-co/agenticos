"""Publish refuses a native-only binding on a model that supports no native tool (#166).

A binding with a local tool behind the provider's runs on a Claude subscription
model; one configured to the provider's tool alone would fail on the first turn,
so the refusal belongs at publish, on the input that causes it.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities import load_builtins
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.claude_subscription import CLAUDE_SUBSCRIPTION_PROVIDER
from app.core.permissions import AuthContext, OrgRoleName
from app.services.agent_registry import AgentRegistryService

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


async def _problems(provider: str | None, *bindings: CapabilityBindingSpec):
    load_builtins()
    spec = AgentSpec(name="Architect", capabilities=list(bindings))
    profile = None if provider is None else SimpleNamespace(provider=provider)
    with patch(
        "app.services.agent_registry.credential_repo.get_profile",
        new=AsyncMock(return_value=profile),
    ):
        return await AgentRegistryService(MagicMock())._native_only_problems(
            _ctx(), spec, uuid.uuid4()
        )


@pytest.mark.parametrize(
    ("capability", "config", "field"),
    [
        ("web_fetch", {"method": "native"}, "method"),
        ("web_research", {"method": "native"}, "method"),
        ("tool_search", {"strategy": "bm25"}, "strategy"),
        ("tool_search", {"strategy": "regex"}, "strategy"),
    ],
)
async def test_a_native_only_binding_is_refused_on_a_subscription_model(capability, config, field):
    problems = await _problems(
        CLAUDE_SUBSCRIPTION_PROVIDER, CapabilityBindingSpec(id=capability, config=config)
    )
    [message] = problems.messages
    assert "Claude subscription models support none" in message
    assert problems.fields == [{"field": f"capabilities.{capability}.{field}", "message": message}]


@pytest.mark.parametrize("strategy", ["auto", "keywords", "local_bm25"])
async def test_bindings_with_a_local_tool_publish_on_a_subscription_model(strategy):
    problems = await _problems(
        CLAUDE_SUBSCRIPTION_PROVIDER,
        CapabilityBindingSpec(id="web_fetch", config={"method": "auto"}),
        CapabilityBindingSpec(id="web_research"),
        CapabilityBindingSpec(id="tool_search", config={"strategy": strategy}),
    )
    assert problems.messages == []


async def test_a_native_only_binding_publishes_on_a_model_with_native_tools():
    problems = await _problems(
        "anthropic", CapabilityBindingSpec(id="web_fetch", config={"method": "native"})
    )
    assert problems.messages == []


async def test_a_missing_profile_is_left_to_the_model_check():
    problems = await _problems(
        None, CapabilityBindingSpec(id="web_fetch", config={"method": "native"})
    )
    assert problems.messages == []


async def test_an_invalid_config_is_left_to_the_binding_check():
    problems = await _problems(
        CLAUDE_SUBSCRIPTION_PROVIDER,
        CapabilityBindingSpec(id="web_fetch", config={"method": "carrier pigeon"}),
    )
    assert problems.messages == []
