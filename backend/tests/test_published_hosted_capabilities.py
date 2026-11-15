"""Hosted launch hints describe frozen configuration without enabling any tools."""

from copy import deepcopy
from uuid import uuid4

import pytest

from app.agents.spec import CapabilityBindingSpec
from app.core.config import settings
from app.schemas.agent import AgentRead
from app.services import agent_registry


def _binding(
    capability: str,
    config: dict[str, object] | None = None,
    *,
    enabled: bool = True,
    secret: bool = False,
) -> CapabilityBindingSpec:
    return CapabilityBindingSpec(
        id=capability,
        config=dict(config or {}),
        enabled=enabled,
        secret_id=uuid4() if secret else None,
    )


@pytest.fixture(autouse=True)
def _configured_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser.internal", "renderer.internal"]
    )
    monkeypatch.setattr(settings, "ARTIFACT_RENDER_CDP_URL", "http://renderer.internal:9222")

    async def no_probe(*args: object, **kwargs: object) -> None:
        raise AssertionError("Listing hosted configuration must not probe a network address")

    monkeypatch.setattr(agent_registry, "check_address", no_probe)


@pytest.mark.parametrize(
    ("config", "secret", "expected"),
    [
        ({}, False, False),
        ({"cdp_url": "http://browser.internal:9222"}, False, True),
        ({"connection": "built_in", "cdp_url": "ws://browser.internal:9222"}, False, True),
        (
            {
                "connection": "proxy",
                "cdp_url": "http://browser.internal:9222",
                "proxy_url": "https://proxy.example:443",
            },
            False,
            True,
        ),
        ({"connection": "proxy", "cdp_url": "http://browser.internal:9222"}, False, False),
        (
            {
                "connection": "proxy",
                "cdp_url": "http://browser.internal:9222",
                "proxy_url": "file:///tmp/proxy",
            },
            False,
            False,
        ),
        (
            {
                "connection": "proxy",
                "cdp_url": "http://browser.internal:9222",
                "proxy_url": "socks5://proxy.example:1080",
            },
            True,
            False,
        ),
        ({"connection": "hosted", "hosted_url": "wss://browser.example"}, True, True),
        ({"connection": "hosted", "hosted_url": "wss://browser.example"}, False, False),
        ({"connection": "hosted"}, True, False),
        ({"connection": "hosted", "hosted_url": "file:///tmp/browser"}, True, False),
        ({"connection": "local", "cdp_url": "http://browser.internal:9222"}, False, False),
        ({"connection": "auto", "cdp_url": "http://browser.internal:9222"}, False, False),
        ({"cdp_url": "http://unapproved.internal:9222"}, False, False),
        ({"cdp_url": "http://renderer.internal:9222"}, False, False),
        ({"cdp_url": "file:///tmp/browser"}, False, False),
        ({"cdp_url": "http://["}, False, False),
        ({"cdp_url": "http://browser.internal:bad-port"}, False, False),
        ({"cdp_url": "http://browser.internal:9222", "vision": "invalid"}, False, False),
    ],
)
def test_only_configured_hosted_browsers_are_advertised(
    config: dict[str, object], secret: bool, expected: bool
) -> None:
    bindings = [_binding("browser_use", config, secret=secret)]
    assert agent_registry._published_hosted_capabilities(bindings) == (
        ["browser_use"] if expected else []
    )


@pytest.mark.parametrize(
    ("computer", "sandbox", "secret", "expected"),
    [
        ({"desktop": "sandbox"}, {"backend": "service", "runtime": "desktop"}, False, True),
        (
            {"desktop": "sandbox"},
            {"backend": "service", "runtime": "desktop", "connection_id": str(uuid4())},
            False,
            True,
        ),
        (
            {"desktop": "sandbox"},
            {"backend": "service", "runtime": "desktop", "connection_id": None},
            False,
            True,
        ),
        (
            {"desktop": "sandbox"},
            {"backend": "service", "runtime": "desktop", "connection_id": "invalid"},
            False,
            False,
        ),
        ({"desktop": "sandbox"}, {"backend": "state", "runtime": "desktop"}, False, False),
        ({"desktop": "sandbox"}, {"backend": "local", "runtime": "desktop"}, False, False),
        ({"desktop": "sandbox"}, None, False, False),
        ({"desktop": "sandbox"}, {}, False, False),
        ({"desktop": "sandbox"}, {"backend": "service"}, False, False),
        ({"desktop": "sandbox"}, {"backend": "service", "runtime": "python"}, False, False),
        ({"desktop": "sandbox"}, {"backend": "unknown", "runtime": "desktop"}, False, False),
        ({"desktop": "sandbox"}, {"backend": "service", "runtime": 7}, False, False),
        ({"desktop": "auto"}, {"backend": "service", "runtime": "desktop"}, False, False),
        ({}, {"backend": "service", "runtime": "desktop"}, False, False),
        ({"desktop": "local"}, {"backend": "service", "runtime": "desktop"}, False, False),
        ({"desktop": "daemon", "daemon_url": "http://computer.example:8765"}, None, True, False),
        ({"desktop": "e2b"}, None, True, True),
        ({"desktop": "e2b"}, None, False, False),
        ({"desktop": "unknown"}, None, False, False),
        ({"desktop": "e2b", "screen_width": 1}, None, True, False),
    ],
)
def test_only_explicit_supported_hosted_desktops_are_advertised(
    computer: dict[str, object], sandbox: dict[str, object] | None, secret: bool, expected: bool
) -> None:
    bindings = [_binding("computer_use", computer, secret=secret)]
    if sandbox is not None:
        bindings.append(_binding("sandbox", sandbox))
    assert agent_registry._published_hosted_capabilities(bindings) == (
        ["computer_use"] if expected else []
    )


@pytest.mark.parametrize("disabled", ["browser_use", "computer_use", "sandbox"])
def test_explicit_disables_are_preserved(disabled: str) -> None:
    bindings = [
        _binding(
            "browser_use",
            {"cdp_url": "http://browser.internal:9222"},
            enabled=disabled != "browser_use",
        ),
        _binding("computer_use", {"desktop": "sandbox"}, enabled=disabled != "computer_use"),
        _binding(
            "sandbox", {"backend": "service", "runtime": "desktop"}, enabled=disabled != "sandbox"
        ),
    ]
    expected = ["computer_use"] if disabled == "browser_use" else ["browser_use"]
    assert agent_registry._published_hosted_capabilities(bindings) == expected


def test_listing_targets_neither_adds_bindings_nor_changes_limits_or_credentials() -> None:
    assert agent_registry._published_hosted_capabilities([]) == []
    bindings = [
        _binding("thinking"),
        _binding(
            "browser_use",
            {"cdp_url": "http://browser.internal:9222", "allowed_domains": ["example.com"]},
        ),
        _binding("computer_use", {"desktop": "e2b", "max_actions": 20}, secret=True),
    ]
    before = deepcopy(bindings)
    assert agent_registry._published_hosted_capabilities(bindings) == [
        "browser_use",
        "computer_use",
    ]
    assert bindings == before


@pytest.mark.security
def test_unknown_hosted_configuration_is_distinct_from_none_and_grants_no_run_permission() -> None:
    row = AgentRead(
        id=uuid4(),
        slug="agent",
        name="Agent",
        status="published",
        visibility="private",
        categories=[],
        tags=[],
    )
    assert row.model_dump()["published_hosted_capabilities"] is None
    row.published_hosted_capabilities = []
    assert row.model_dump()["published_hosted_capabilities"] == []
    row.published_hosted_capabilities = ["browser_use"]
    assert row.can_run is False
