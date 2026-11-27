"""Only live registered pages can be exposed or selected, under the physical driver."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import WebSocketDisconnect

from app.agents.capabilities.browser_use import _page
from app.core.exceptions import ConflictError
from app.schemas.conversation_environment import ConversationBrowserTab, ConversationBrowserTabs
from app.services import conversation_environment_runtime as runtime
from app.services import conversation_environment_stream as stream
from app.services.conversation_environment_resources import (
    BrowserEnvironmentResource,
    StoredBrowserRoute,
)
from tests import test_conversation_environment_stream as sockets

case = sockets.case
pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def run(case):
    await stream.stream_environment(
        case.socket,
        auth_token="session-token",
        conversation_id=case.conversation,
        environment_id=case.identity,
        execution_target="agent",
        tabs_enabled=True,
    )


@pytest.mark.parametrize("with_route", [False, True])
async def test_cdp_list_exposes_only_exact_registered_live_page_identities(monkeypatch, with_route):
    answer = {
        "targetInfos": [
            {
                "targetId": "a",
                "browserContextId": "owned",
                "type": "page",
                "url": "https://one.test/",
                "title": "One",
            },
            {
                "targetId": "b",
                "browserContextId": "other-owner",
                "type": "page",
                "url": "https://private.test/",
                "title": "Private",
            },
            {
                "targetId": "unknown",
                "browserContextId": "owned",
                "type": "page",
                "url": "https://secret.test/",
                "title": "Secret",
            },
            {
                "targetId": "worker",
                "browserContextId": "owned",
                "type": "service_worker",
                "url": "https://worker.test/",
            },
            {"targetId": "default-tab", "type": "page", "url": "about:blank"},
        ]
    }
    client = SimpleNamespace(
        send=SimpleNamespace(Target=SimpleNamespace(getTargets=AsyncMock(return_value=answer)))
    )

    @asynccontextmanager
    async def connected(_url, _route):
        yield client

    monkeypatch.setattr(_page, "_browser_client", connected)
    route = StoredBrowserRoute(locale="pl") if with_route else None
    resource = BrowserEnvironmentResource(
        environment_id=uuid4(),
        organization_id=uuid4(),
        cdp_url="http://private-cdp",
        route=route,
        tabs={
            "main": _page.BrowserTarget(context_id="owned", target_id="a"),
            "closed": _page.BrowserTarget(context_id="owned", target_id="closed"),
            "wrong-context": _page.BrowserTarget(context_id="owned", target_id="b"),
            "worker": _page.BrowserTarget(context_id="owned", target_id="worker"),
        },
    )
    result = await runtime.browser_tabs(resource)
    assert result.tabs == [ConversationBrowserTab(id="main", url="https://one.test/", title="One")]
    assert result.active_tab_id == "main"
    assert all(
        secret not in result.model_dump_json()
        for secret in [
            "private-cdp",
            "other-owner",
            "Private",
            "Secret",
            "browserContextId",
            "targetId",
        ]
    )
    # A new page added by the real agent after admission appears on the next read.
    resource.tabs["second"] = _page.BrowserTarget(context_id="owned", target_id="new")
    answer["targetInfos"].append(
        {
            "targetId": "new",
            "browserContextId": "owned",
            "type": "page",
            "url": "https://two.test/",
            "title": "Two",
        }
    )
    resource.active = "second"
    assert [tab.id for tab in (await runtime.browser_tabs(resource)).tabs] == ["main", "second"]
    answer["targetInfos"].pop()
    assert (await runtime.browser_tabs(resource)).active_tab_id is None


async def test_malformed_provider_tab_metadata_is_a_controlled_adapter_error(monkeypatch):
    client = SimpleNamespace(
        send=SimpleNamespace(
            Target=SimpleNamespace(
                getTargets=AsyncMock(return_value={"targetInfos": [{"title": "private-secret"}]})
            )
        )
    )

    @asynccontextmanager
    async def connected(_url, _route):
        yield client

    monkeypatch.setattr(_page, "_browser_client", connected)
    with pytest.raises(_page.EndpointError, match="could not report") as failure:
        await _page.open_browser_pages(cdp_url="private-endpoint", route=None, targets={})
    assert "private-secret" not in str(failure.value)


@pytest.fixture
def browser(case, monkeypatch):
    case.resource = BrowserEnvironmentResource(
        environment_id=case.identity,
        organization_id=case.ctx.organization_id,
        cdp_url="http://private",
        tabs={
            "main": _page.BrowserTarget(context_id="owned-a", target_id="a"),
            "second": _page.BrowserTarget(context_id="owned-b", target_id="b"),
        },
    )
    case.row.kind = case.read.kind = "browser"
    case.row.expires_at = datetime.now(UTC) + timedelta(minutes=15)
    case.touches, case.leases, case.stores = [], [], []

    async def live(_ctx, _conv, _id, _target, *, lock=False, touch=False):
        if touch:
            assert lock
            case.touches.append(True)
        return case.row, case.resolved, case.resource.model_copy(deep=True)

    async def store(_self, row, resource):
        case.stores.append(resource.active)
        case.resource = resource
        row.resource_ciphertext = f"sealed-{len(case.stores)}"

    monkeypatch.setattr(stream.ConversationEnvironmentService, "live", AsyncMock(side_effect=live))
    monkeypatch.setattr(stream.ConversationEnvironmentService, "replace_resource", store)

    async def tabs(resource):
        return ConversationBrowserTabs(
            environment_id=case.identity,
            tabs=[
                ConversationBrowserTab(id=key, title=key, url=f"https://{key}.test/")
                for key in resource.tabs
            ],
            active_tab_id=resource.active,
        )

    monkeypatch.setattr(stream.runtime, "browser_tabs", AsyncMock(side_effect=tabs))

    class Driver:
        def __init__(self, _key, _ctx, control, check):
            self.token = uuid4()
            self.check, self.control, self.closed = check, control, 0
            case.leases.append(self)

        async def acquire(self):
            await self.check(case.db)

        async def require(self):
            await self.check(case.db)

        async def close(self):
            self.closed += 1

    monkeypatch.setattr(stream, "EnvironmentDriver", Driver)

    async def held(_db, _key):
        return SimpleNamespace(
            lease_token=case.leases[-1].token, lease_until=datetime.now(UTC) + timedelta(minutes=1)
        )

    monkeypatch.setattr(stream.environments, "driver", AsyncMock(side_effect=held))
    return case


async def test_idle_selection_reuses_the_live_target_without_granting_input(browser):
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": "second"}),
        json.dumps({"type": "click", "x": 1, "y": 2}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert browser.resource.active == "second" and browser.stores == ["second"]
    assert (
        len(browser.leases) == 1
        and browser.leases[0].control == "layout"
        and browser.leases[0].closed == 1
    )
    assert browser.touches == [True]
    runtime.perform.assert_not_awaited()
    assert any(
        frame["type"] == "environment_tabs" and frame["data"]["active_tab_id"] == "second"
        for frame in browser.frames
    )
    assert not any(
        frame["type"] == "browser_event" and frame["data"]["kind"] == "browser_held"
        for frame in browser.frames
    )


async def test_selection_reuses_its_own_human_lease(browser):
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "take_over"}),
        json.dumps({"type": "activate_tab", "tab_id": "second"}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert len(browser.leases) == 1 and browser.leases[0].control == "human"
    assert browser.resource.active == "second" and browser.leases[0].closed == 1


@pytest.mark.parametrize("selection", ["missing", "provider-target-id"])
async def test_forged_or_stale_logical_page_selection_never_changes_the_journal(browser, selection):
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": selection}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert browser.stores == [] and browser.touches == [] and browser.resource.active == "main"
    assert browser.leases[0].closed == 1


async def test_closed_actual_target_refuses_selection_without_recreating_a_page(browser):
    async def closed(resource):
        return ConversationBrowserTabs(
            environment_id=browser.identity,
            tabs=[ConversationBrowserTab(id="main", title="Main", url="https://main.test")],
            active_tab_id="main",
        )

    runtime.browser_tabs.side_effect = closed
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": "second"}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert browser.stores == [] and browser.touches == [] and browser.leases[0].closed == 1


async def test_selection_cannot_steal_a_busy_agent_or_other_socket_driver(browser, monkeypatch):
    async def busy(_self):
        raise ConflictError(message="Busy")

    monkeypatch.setattr(stream.EnvironmentDriver, "acquire", busy)
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": "second"}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert browser.stores == [] and browser.touches == [] and browser.leases[0].closed == 1


async def test_reselecting_the_current_page_does_not_extend_idle(browser):
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": "main"}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert browser.touches == [] and browser.stores == []


async def test_view_only_tab_selection_never_claims_a_driver_or_changes_idle(browser):
    browser.read.can_control = False
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": "second"}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert browser.leases == [] and browser.stores == [] and browser.touches == []


async def test_older_clients_never_receive_unknown_tab_frames_or_activate_pages(browser):
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": "second"}),
        WebSocketDisconnect(),
    ]
    await sockets.run(browser)
    runtime.browser_tabs.assert_not_awaited()
    assert not any(frame["type"] == "environment_tabs" for frame in browser.frames)
    assert browser.leases == [] and browser.stores == [] and browser.touches == []


@pytest.mark.parametrize("kind,key", [("desktop", "physical"), ("browser", None)])
async def test_tab_activation_requires_a_browser_and_retained_physical_key(browser, kind, key):
    browser.row.kind = kind
    browser.row.resource_key = key
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": "second"}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert browser.leases == [] and browser.stores == [] and browser.touches == []


@pytest.mark.parametrize("driver_state", ["missing", "different", "expired"])
async def test_stale_layout_token_cannot_publish_a_page_selection(
    browser, monkeypatch, driver_state
):
    async def held(_db, _key):
        if driver_state == "missing":
            return None
        return SimpleNamespace(
            lease_token=uuid4() if driver_state == "different" else browser.leases[-1].token,
            lease_until=datetime.now(UTC)
            + timedelta(seconds=-1 if driver_state == "expired" else 60),
        )

    monkeypatch.setattr(stream.environments, "driver", held)
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": "second"}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert (
        browser.stores == [] and browser.resource.active == "main" and browser.leases[0].closed == 1
    )


async def test_changed_page_handle_is_not_substituted_after_metadata_returns(browser):
    original = runtime.browser_tabs.side_effect
    calls = 0

    async def retarget(resource):
        nonlocal calls
        calls += 1
        metadata = await original(resource)
        if calls == 2:
            browser.resource.tabs["second"] = _page.BrowserTarget(
                context_id="new-context", target_id="new-target"
            )
        return metadata

    runtime.browser_tabs.side_effect = retarget
    browser.socket.receive_text.side_effect = [
        json.dumps({"type": "activate_tab", "tab_id": "second"}),
        WebSocketDisconnect(),
    ]
    await run(browser)
    assert browser.stores == [] and browser.resource.active == "main"


async def test_metadata_racing_a_new_sealed_selection_is_not_published(browser):
    async def competing_update(resource):
        browser.row.resource_ciphertext = "newer-agent-journal"
        return ConversationBrowserTabs(
            environment_id=browser.identity,
            tabs=[ConversationBrowserTab(id="main", title="Stale", url="https://old.test")],
            active_tab_id="main",
        )

    runtime.browser_tabs.side_effect = competing_update
    browser.socket.receive_text.side_effect = WebSocketDisconnect()
    await run(browser)
    assert not any(frame["type"] == "environment_tabs" for frame in browser.frames)
    assert browser.stores == [] and browser.touches == []
