"""The retained environment boundary preserves old specs and private identities."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.capabilities.browser_use import WebBrowserConfig
from app.agents.capabilities.computer_use import ComputerUseConfig
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.conversation_environment import (
    ConversationEnvironment,
    ConversationEnvironmentDriver,
)
from app.schemas.conversation_environment import ConversationEnvironmentStart
from app.services import conversation_environments as lifecycle
from app.services.conversation_environment_resources import (
    ENVIRONMENT_RESOURCE,
    BrowserEnvironmentResource,
)

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("config_type", [WebBrowserConfig, ComputerUseConfig])
def test_stored_bindings_keep_run_lifetime_until_explicitly_enabled(config_type):
    old = config_type.model_validate({})
    assert old.session_lifetime == "run"
    selected = config_type.model_validate(
        {"session_lifetime": "conversation", "session_idle_seconds": 900}
    )
    assert selected.session_lifetime == "conversation"
    assert selected.session_idle_seconds == 900


@pytest.mark.parametrize("seconds", [59, 86401])
@pytest.mark.parametrize("config_type", [WebBrowserConfig, ComputerUseConfig])
def test_retention_cannot_be_unbounded(config_type, seconds):
    with pytest.raises(ValidationError):
        config_type.model_validate(
            {"session_lifetime": "conversation", "session_idle_seconds": seconds}
        )


def test_start_never_accepts_a_provider_ref_or_fake_run():
    with pytest.raises(ValidationError):
        ConversationEnvironmentStart.model_validate(
            {"agent_id": str(uuid4()), "run_id": str(uuid4()), "provider_ref": "arbitrary"}
        )


def test_effective_idle_respects_deployment_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "CONVERSATION_ENVIRONMENT_MAX_IDLE_SECONDS", 120)
    before = datetime.now(UTC)
    assert (
        before + timedelta(seconds=119)
        <= lifecycle.idle_until(86400)
        <= datetime.now(UTC) + timedelta(seconds=120)
    )


@pytest.mark.security
def test_api_keys_cannot_promote_their_issuer_to_a_manual_owner():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner", api_key_id=uuid4())
    with pytest.raises(AuthorizationError):
        lifecycle.personal_owner(ctx)


@pytest.mark.security
async def test_changed_selector_never_projects_an_old_live_provider(monkeypatch):
    row = ConversationEnvironment(
        id=uuid4(),
        kind="desktop",
        state="ready",
        resource_key="private-key",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    driver = AsyncMock()
    monkeypatch.setattr(lifecycle.environments, "driver", driver)
    result = await lifecycle.ConversationEnvironmentService(AsyncMock())._read(
        row,
        uuid4(),
        "desktop",
        "project",
        refusal=lifecycle.ConversationEnvironmentRefusal(
            code="environment_changed", message="The target changed"
        ),
    )
    assert result.id is None
    assert result.state == "not_started"
    assert result.execution_target == "project"
    assert result.control == "none"
    assert not result.can_control
    assert result.expires_at is None
    driver.assert_not_awaited()


async def test_expired_authoritative_projection_cannot_claim_live_control(monkeypatch):
    row = ConversationEnvironment(
        id=uuid4(),
        kind="browser",
        state="ready",
        resource_key="physical",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    held = ConversationEnvironmentDriver(
        resource_key="physical",
        control="human",
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    monkeypatch.setattr(lifecycle.environments, "driver", AsyncMock(return_value=held))
    result = await lifecycle.ConversationEnvironmentService(AsyncMock())._read(
        row, uuid4(), "browser", "agent"
    )
    assert result.state == "expired"
    assert result.control == "none"
    assert not result.can_control
    assert result.refusal is not None
    assert result.refusal.code == "environment_expired"


def test_private_browser_resource_retains_exact_target_and_rejects_unknown_fields():
    from app.agents.capabilities.browser_use._page import BrowserTarget

    resource = BrowserEnvironmentResource(
        environment_id=uuid4(),
        organization_id=uuid4(),
        cdp_url="http://private-browser:9222",
        tabs={"main": BrowserTarget(context_id="owned-context", target_id="owned-target")},
    )
    restored = ENVIRONMENT_RESOURCE.validate_json(resource.model_dump_json())
    assert isinstance(restored, BrowserEnvironmentResource)
    assert restored.tabs["main"].context_id == "owned-context"
    assert restored.tabs["main"].target_id == "owned-target"
    assert "private-browser" not in repr(resource)
    with pytest.raises(ValidationError):
        ENVIRONMENT_RESOURCE.validate_python(
            {**resource.model_dump(), "injected_transport": "other"}
        )


def test_vault_browser_route_round_trip_preserves_private_transport_without_public_repr():
    from pydantic import SecretStr

    from app.agents.capabilities.browser_use._route import BrowserRoute
    from app.services.conversation_environment_resources import StoredBrowserRoute

    route = BrowserRoute(
        proxy_server="http://proxy.invalid",
        proxy_username="private-user",
        proxy_password=SecretStr("private-pass"),
        remote_url=SecretStr("http://remote.invalid/private-token"),
        remote_address="private-address",
        timezone="Europe/Warsaw",
        locale="pl",
    )
    captured = StoredBrowserRoute.capture(route)
    assert captured is not None and captured.restore() == route
    assert "private-pass" not in repr(captured)
    assert "private-token" not in repr(captured)
    empty = StoredBrowserRoute.capture(BrowserRoute())
    assert empty is not None and empty.restore() == BrowserRoute()


def test_environment_repr_excludes_encrypted_cleanup_credentials():
    row = ConversationEnvironment(
        id=uuid4(), kind="browser", state="ready", resource_ciphertext="private-sealed-credential"
    )
    assert "private-sealed-credential" not in repr(row)
    assert str(row.id) in repr(row)
