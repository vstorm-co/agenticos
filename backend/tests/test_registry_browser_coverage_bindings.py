"""Registry validation preserves browser credential authority and field errors."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities import load_builtins
from app.agents.spec import CapabilityBindingSpec
from app.core.config import settings
from app.core.permissions import AuthContext
from app.services.agent_registry import AgentRegistryService
from app.services.browser_credentials import _bindings

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("problem", [None, _bindings.BINDING_REFUSAL])
@pytest.mark.parametrize(
    ("connection", "endpoint", "provisioned_endpoint", "expected"),
    [
        ("built_in", "http://browser:9222/", "http://browser:9222", True),
        ("built_in", "http://browser:9222", "", False),
        ("built_in", "http://another-browser:9222", "http://browser:9222", False),
        ("hosted", "http://browser:9222", "http://browser:9222", False),
    ],
)
async def test_binding_validation_keeps_the_credential_check_and_its_field_problem(
    monkeypatch: pytest.MonkeyPatch,
    problem: str | None,
    connection: str,
    endpoint: str,
    provisioned_endpoint: str,
    expected: bool,
) -> None:
    load_builtins()
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", provisioned_endpoint)
    credential_id, agent_id = uuid4(), uuid4()
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    binding = CapabilityBindingSpec(
        id="browser_use",
        config={
            "connection": connection,
            "cdp_url": endpoint,
            "browser_credential_ids": [str(credential_id)],
        },
    )
    check = AsyncMock(return_value=problem)
    monkeypatch.setattr(_bindings, "binding_problem", check)
    db = AsyncMock()
    result = await AgentRegistryService(db)._binding_problems(ctx, binding, agent_id=agent_id)
    check.assert_awaited_once_with(
        db, ctx, [credential_id], agent_id=agent_id, provisioned=expected
    )
    field_problems = [
        item
        for item in result.fields
        if item["field"] == "capabilities.browser_use.config.browser_credential_ids"
    ]
    if problem is None:
        assert field_problems == []
    else:
        assert field_problems == [
            {
                "field": "capabilities.browser_use.config.browser_credential_ids",
                "message": problem,
            }
        ]
        assert problem in result.messages
