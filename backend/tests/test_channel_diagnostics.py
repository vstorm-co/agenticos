"""Readiness is scoped and never borrows another person's MCP credentials."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.spec import PersonalMcpServerRef
from app.core.exceptions import NotFoundError
from app.repositories import (
    agent_exposure_repo,
    channel_bot_repo,
    channel_identity_repo,
    mcp_connection_repo,
    organization_assistant_repo,
)
from app.services.channel_bot import ChannelBotService
from app.services.channels import connection_state

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def assistant_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(organization_assistant_repo, "for_agent", AsyncMock(return_value=None))


@pytest.mark.parametrize(
    "linked,connected,published",
    [(False, False, True), (True, False, True), (True, True, True), (True, True, False)],
)
async def test_personal_checks_describe_only_this_caller(monkeypatch, linked, connected, published):
    org, user, botid = uuid4(), uuid4(), uuid4()
    bot = SimpleNamespace(id=botid, platform="mattermost", is_active=True, webhook_mode=False)
    monkeypatch.setattr(channel_bot_repo, "get_for_org", AsyncMock(return_value=bot))
    monkeypatch.setattr(
        connection_state, "read", AsyncMock(return_value=SimpleNamespace(state="up", reason=None))
    )
    monkeypatch.setattr(
        agent_exposure_repo,
        "bound_to_bot",
        AsyncMock(
            return_value=SimpleNamespace(is_active=True, agent_id=uuid4(), environment_id=None)
        ),
    )
    monkeypatch.setattr(
        channel_identity_repo,
        "list_for_user",
        AsyncMock(return_value=[SimpleNamespace(platform="mattermost")] if linked else []),
    )
    accounts = AsyncMock(return_value=[object()] if connected else [])
    monkeypatch.setattr(mcp_connection_repo, "list_user_scoped_by_catalog_key", accounts)
    published_spec = SimpleNamespace(
        mcp_servers=[PersonalMcpServerRef(account="personal", catalog_key="notion")]
    )
    registry = AsyncMock(
        return_value=published_spec if published else None,
    )
    monkeypatch.setattr(ChannelBotService, "_diagnostic_spec", registry)
    result = await ChannelBotService(MagicMock(), org).diagnostics(
        botid, SimpleNamespace(user_id=user)
    )
    assert not result.credentials_probed and result.account_scope == "current_user"
    checks = {check.code: check.status for check in result.checks}
    assert checks["identity"] == ("ok" if linked else "warning")
    assert checks["published"] == ("ok" if published else "blocked")
    if published:
        assert checks["personal_service"] == ("ok" if linked and connected else "warning")
        assert accounts.await_args.kwargs["user_id"] == user
    else:
        accounts.assert_not_awaited()


async def test_a_foreign_bot_is_missing_before_reading_any_diagnostics(monkeypatch):
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(channel_bot_repo, "get_for_org", lookup)
    org = uuid4()
    with pytest.raises(NotFoundError):
        await ChannelBotService(MagicMock(), org).diagnostics(
            uuid4(), SimpleNamespace(user_id=uuid4())
        )
    assert lookup.await_args.kwargs["organization_id"] == org


@pytest.mark.parametrize(
    "platform,webhook,credential,state,expected",
    [
        ("slack", False, False, "up", "blocked"),
        ("slack", True, False, None, "blocked"),
        ("slack", True, True, None, "unknown"),
        ("slack", False, True, "down", "blocked"),
        ("slack", False, True, None, "unknown"),
        ("mattermost", True, False, None, "blocked"),
        ("mattermost", True, True, None, "unknown"),
        ("mattermost", False, True, "up", "ok"),
        ("telegram", True, False, None, "blocked"),
        ("telegram", True, True, None, "unknown"),
        ("telegram", False, False, "up", "ok"),
    ],
)
async def test_transport_health_never_claims_an_unobserved_webhook_is_ready(
    monkeypatch, platform, webhook, credential, state, expected
):
    bot = SimpleNamespace(
        id=uuid4(),
        platform=platform,
        is_active=False,
        webhook_mode=webhook,
        slack_app_token_encrypted="sealed" if credential else None,
        slack_signing_secret_encrypted="sealed" if credential else None,
        webhook_secret_encrypted="sealed" if credential else None,
    )
    monkeypatch.setattr(channel_bot_repo, "get_for_org", AsyncMock(return_value=bot))
    monkeypatch.setattr(
        connection_state,
        "read",
        AsyncMock(
            return_value=None
            if state is None
            else SimpleNamespace(state=state, reason="Reconnect" if state == "down" else None)
        ),
    )
    monkeypatch.setattr(agent_exposure_repo, "bound_to_bot", AsyncMock(return_value=None))
    identities = AsyncMock()
    monkeypatch.setattr(channel_identity_repo, "list_for_user", identities)
    result = await ChannelBotService(MagicMock(), uuid4()).diagnostics(
        bot.id, SimpleNamespace(user_id=None)
    )
    states = {check.code: check.status for check in result.checks}
    assert states == {
        "active": "blocked",
        "transport": expected,
        "binding": "blocked",
        "identity": "warning",
    }
    identities.assert_not_awaited()


async def test_nonpersonal_bindings_and_api_keys_do_not_borrow_a_persons_account(monkeypatch):
    bot = SimpleNamespace(
        id=uuid4(),
        platform="telegram",
        is_active=True,
        webhook_mode=True,
        webhook_secret_encrypted="sealed",
    )
    monkeypatch.setattr(channel_bot_repo, "get_for_org", AsyncMock(return_value=bot))
    monkeypatch.setattr(
        agent_exposure_repo,
        "bound_to_bot",
        AsyncMock(
            return_value=SimpleNamespace(is_active=True, agent_id=uuid4(), environment_id=None)
        ),
    )
    spec = SimpleNamespace(
        mcp_servers=[
            SimpleNamespace(account="org"),
            PersonalMcpServerRef(account="personal", catalog_key="notion"),
        ]
    )
    monkeypatch.setattr(ChannelBotService, "_diagnostic_spec", AsyncMock(return_value=spec))
    accounts = AsyncMock()
    monkeypatch.setattr(mcp_connection_repo, "list_user_scoped_by_catalog_key", accounts)
    result = await ChannelBotService(MagicMock(), uuid4()).diagnostics(
        bot.id, SimpleNamespace(user_id=None)
    )
    accounts.assert_not_awaited()
    assert result.checks[-1].code == "personal_service" and result.checks[-1].status == "warning"


@pytest.mark.parametrize(
    "state",
    [
        "published",
        "assistant_off",
        "assistant_on",
        "missing",
        "archived",
        "draft",
        "environment",
        "foreign_environment",
        "foreign_version",
        "missing_version",
    ],
)
async def test_publication_inspection_uses_organization_scope_and_no_run_authorization(
    monkeypatch, state
):
    from app.agents.spec import AgentSpec
    from app.repositories import agent_environment_repo, agent_repo
    from app.services.agent_registry import AgentRegistryService

    org, agent_id, version_id = uuid4(), uuid4(), uuid4()
    agent = SimpleNamespace(
        id=agent_id,
        current_version_id=None if state == "draft" else version_id,
        status="archived" if state == "archived" else "active",
    )
    lookup = AsyncMock(return_value=None if state == "missing" else agent)
    monkeypatch.setattr(agent_repo, "get", lookup)
    if state in {"assistant_off", "assistant_on"}:
        monkeypatch.setattr(
            organization_assistant_repo,
            "for_agent",
            AsyncMock(return_value=SimpleNamespace(enabled=state == "assistant_on")),
        )
    binding = SimpleNamespace(
        agent_id=agent_id,
        environment_id=uuid4() if state in {"environment", "foreign_environment"} else None,
    )
    environment_version = uuid4()
    environment = SimpleNamespace(
        agent_id=uuid4() if state == "foreign_environment" else agent_id,
        version_id=environment_version,
    )
    monkeypatch.setattr(agent_environment_repo, "get", AsyncMock(return_value=environment))
    version_lookup = AsyncMock(
        return_value=None
        if state == "missing_version"
        else SimpleNamespace(
            agent_id=uuid4() if state == "foreign_version" else agent_id,
            spec=AgentSpec(name="Sales").model_dump(),
        )
    )
    monkeypatch.setattr(agent_repo, "get_version", version_lookup)
    run_check = AsyncMock(side_effect=AssertionError("Diagnostic must not require agents:run"))
    monkeypatch.setattr(AgentRegistryService, "get_runnable_spec", run_check)
    result = await ChannelBotService(MagicMock(), org)._diagnostic_spec(binding)
    assert (result is not None) is (state in {"published", "environment", "assistant_on"})
    assert lookup.await_args.kwargs["organization_id"] == org
    if result is not None:
        assert version_lookup.await_args.args[1] == (
            environment_version if state == "environment" else version_id
        )
        assert version_lookup.await_args.kwargs["organization_id"] == org
    run_check.assert_not_awaited()
