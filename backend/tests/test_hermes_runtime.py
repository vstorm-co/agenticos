"""Hermes receives a conversation identity, never a shared CLI home."""

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from app.agents.audience import RunAudience
from app.agents.capabilities.coding_agent._acp import private_state_scope
from tests.test_coding_agent_acp import _ctx, _local_workspace

pytestmark = pytest.mark.security


def test_private_native_state_changes_with_the_initiating_identity() -> None:
    ctx = _ctx(_local_workspace(), [])
    deps = ctx.deps
    deps.run_person = ctx.workspace.backend.owner_id
    deps.user_id = str(deps.run_person)
    deps.audience = RunAudience(user_id=deps.run_person)
    original = private_state_scope(deps)
    assert original and len(original) == 64 and private_state_scope(deps) == original
    deps.conversation_id = str(uuid4())
    assert private_state_scope(deps) != original
    deps.audience = replace(deps.audience, shared_transcript=True)
    assert private_state_scope(deps) is None
    deps.audience = replace(deps.audience, shared_transcript=False, room_key="room")
    assert private_state_scope(deps) is None
    deps.audience = replace(deps.audience, room_key=None)
    deps.impersonated = True
    assert private_state_scope(deps) is None
    deps.impersonated = False
    deps.user_id = str(uuid4())
    assert private_state_scope(deps) is None
    deps.audience = None
    assert private_state_scope(deps) is None


@pytest.mark.anyio
async def test_the_private_scope_crosses_native_ipc_without_a_path_or_credential() -> None:
    from app.agents.capabilities.coding_agent._acp import DevicePipe

    sent: dict[str, object] = {}

    class Device:
        async def agent_call(
            self, op: str, args: dict[str, Any], *, timeout: float, root: str | None = None
        ) -> dict[str, Any]:
            assert op == "agent.open"
            sent.update(args)
            return {"id": "owned", "protocol": "acp"}

    scope = "a" * 64
    pipe = DevicePipe(Device(), "custom", custom_agent_id="hermes", state_scope=scope)
    await pipe.open()
    assert sent["state_scope"] == scope and sent["custom_agent_id"] == "hermes"
    assert not any(key in sent for key in ["home", "program", "api_key", "auth_token"])
