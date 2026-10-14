"""#2130: where an organization's browses run - its setting, and the route a run gets."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from app.agents.capabilities.browser_use._page import (
    auth_reply,
    context_params,
    user_agent_override,
)
from app.agents.capabilities.browser_use._route import BrowserRoute
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.core.sanitize import SSRFBlockedError
from app.core.secret_kinds import ApiKeySecret, SecretKind
from app.schemas.browser_setting import BrowserMode, BrowserSettingUpdate
from app.services import browser_setting as module
from app.services.browser_setting import BrowserSettingService, check_address

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
SECRET = uuid.uuid4()


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role="owner")


@pytest.fixture
def public(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every name resolves to a public address; nothing is on the operator's list."""
    monkeypatch.setattr(module, "resolve_pinned_url", lambda url, allowed_schemes: None)
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The repositories, the vault and the audit trail, kept in a dict."""
    state: dict[str, Any] = {"row": None, "secret": None, "audited": [], "value": None}

    async def get(db: Any, *, organization_id: uuid.UUID) -> Any:
        return state["row"]

    async def save(db: Any, *, organization_id: uuid.UUID, values: dict[str, Any]) -> Any:
        state["row"] = SimpleNamespace(organization_id=organization_id, updated_at=None, **values)
        return state["row"]

    async def secret(db: Any, secret_id: uuid.UUID, *, organization_id: uuid.UUID) -> Any:
        return state["secret"]

    async def record_audit(db: Any, **entry: Any) -> Any:
        state["audited"].append(entry)
        return SimpleNamespace(**entry)

    monkeypatch.setattr(module.browser_setting_repo, "get", get)
    monkeypatch.setattr(module.browser_setting_repo, "save", save)
    monkeypatch.setattr(module.organization_secret_repo, "get", secret)
    monkeypatch.setattr(module, "record_audit", record_audit)
    notifications = MagicMock()
    notifications.hold_security_audience = AsyncMock(return_value=[])
    notifications.security_event = AsyncMock()
    monkeypatch.setattr(module, "NotificationService", MagicMock(return_value=notifications))
    return state


def _service(state: dict[str, Any]) -> BrowserSettingService:
    service = BrowserSettingService(MagicMock())

    async def resolve(ctx: AuthContext, ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
        value = state["value"]
        return {} if value is None else {ids[0]: ApiKeySecret(api_key=SecretStr(value))}

    service.secrets = MagicMock(resolve_for_bindings=resolve)
    return service


class TestAnAddressIsChecked:
    async def test_a_public_proxy_with_a_port_is_accepted(self, public: None):
        await check_address(
            "http://proxy.example.com:8080", field="proxy_url", schemes=module.PROXY_SCHEMES
        )

    @pytest.mark.parametrize(
        ("url", "words"),
        [
            ("ftp://proxy.example.com:21", "Use a"),
            ("http://user:pw@proxy.example.com:8080", "credentials"),
            ("http://proxy.example.com:port", "not a number"),
            ("http://proxy.example.com", "needs its port"),
        ],
    )
    async def test_a_proxy_address_that_cannot_be_used_names_the_field(
        self, public: None, url: str, words: str
    ):
        with pytest.raises(BadRequestError) as refused:
            await check_address(url, field="proxy_url", schemes=module.PROXY_SCHEMES)
        assert refused.value.details["fields"][0]["field"] == "proxy_url"
        assert words in str(refused.value.message)

    @pytest.mark.security
    async def test_an_address_inside_the_network_is_refused(self, monkeypatch: pytest.MonkeyPatch):
        def refuse(url: str, allowed_schemes: frozenset[str]) -> None:
            raise SSRFBlockedError("Blocked: 10.0.0.5 is a private address")

        monkeypatch.setattr(module, "resolve_pinned_url", refuse)
        monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", [])

        with pytest.raises(BadRequestError, match="private"):
            await check_address(
                "wss://10.0.0.5/", field="remote_url", schemes=module.REMOTE_SCHEMES
            )

    async def test_a_host_the_operator_named_may_be_inside_and_in_the_clear(self, public: None):
        await check_address("ws://browser:9222", field="remote_url", schemes=module.REMOTE_SCHEMES)

    async def test_a_hosted_browser_elsewhere_is_reached_over_tls(self, public: None):
        with pytest.raises(BadRequestError, match="wss"):
            await check_address(
                "ws://cdp.example.com/", field="remote_url", schemes=module.REMOTE_SCHEMES
            )


class TestTheSetting:
    async def test_an_organization_that_never_chose_reads_the_default(self, stored: dict[str, Any]):
        read = await _service(stored).get(_ctx())
        assert read.mode is BrowserMode.BUILT_IN

    async def test_a_proxy_is_saved_audited_by_host_and_read_back(
        self, stored: dict[str, Any], public: None
    ):
        stored["secret"] = SimpleNamespace(kind=SecretKind.API_KEY.value)
        data = BrowserSettingUpdate(
            mode=BrowserMode.PROXY,
            proxy_url="http://proxy.example.com:8080",
            secret_id=SECRET,
            timezone="Europe/Warsaw",
            locale="pl-PL",
        )

        saved = await _service(stored).update(_ctx(), data)

        assert saved.proxy_url == "http://proxy.example.com:8080"
        [entry] = stored["audited"]
        assert entry["action"] == "browser_setting.updated"
        assert entry["details"] == {
            "mode": "proxy",
            "proxy_host": "proxy.example.com",
            "remote_host": None,
        }
        assert (await _service(stored).get(_ctx())).timezone == "Europe/Warsaw"

    @pytest.mark.parametrize(
        ("data", "field"),
        [
            (BrowserSettingUpdate(mode=BrowserMode.PROXY), "proxy_url"),
            (BrowserSettingUpdate(mode=BrowserMode.REMOTE), "remote_url"),
            (BrowserSettingUpdate(timezone="Mars/Olympus_Mons"), "timezone"),
            (BrowserSettingUpdate(secret_id=SECRET), "secret_id"),
            (
                BrowserSettingUpdate(
                    mode=BrowserMode.PROXY,
                    proxy_url="socks5://proxy.example.com:1080",
                    secret_id=SECRET,
                ),
                "secret_id",
            ),
        ],
    )
    async def test_what_cannot_work_is_refused_on_its_field(
        self, stored: dict[str, Any], public: None, data: BrowserSettingUpdate, field: str
    ):
        stored["secret"] = (
            SimpleNamespace(kind=SecretKind.API_KEY.value)
            if "socks5" in str(data.proxy_url)
            else None
        )
        with pytest.raises(BadRequestError) as refused:
            await _service(stored).update(_ctx(), data)
        assert refused.value.details["fields"][0]["field"] == field
        assert stored["row"] is None

    async def test_a_hosted_browser_without_a_key_is_saved(
        self, stored: dict[str, Any], public: None
    ):
        data = BrowserSettingUpdate(mode=BrowserMode.REMOTE, remote_url="wss://connect.example.com")
        assert (
            await _service(stored).update(_ctx(), data)
        ).remote_url == "wss://connect.example.com"


def _row(**values: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "mode": "built_in",
        "proxy_url": None,
        "remote_url": None,
        "remote_key_param": "apiKey",
        "secret_id": None,
        "timezone": None,
        "locale": None,
    }
    fields.update(values)
    return SimpleNamespace(**fields)


class TestTheRouteARunGets:
    async def test_the_default_says_nothing(self, stored: dict[str, Any]):
        assert await _service(stored).resolve(_ctx()) is None
        stored["row"] = _row()
        assert await _service(stored).resolve(_ctx()) is None

    async def test_the_built_in_browser_can_still_say_where_it_is(self, stored: dict[str, Any]):
        stored["row"] = _row(timezone="Europe/Warsaw", locale="pl-PL")
        assert await _service(stored).resolve(_ctx()) == BrowserRoute(
            timezone="Europe/Warsaw", locale="pl-PL"
        )

    async def test_a_proxy_carries_its_credentials_masked(
        self, stored: dict[str, Any], public: None
    ):
        stored["row"] = _row(
            mode="proxy", proxy_url="http://proxy.example.com:8080", secret_id=SECRET
        )
        stored["value"] = "ada:s3cret"

        route = await _service(stored).resolve(_ctx())

        assert route is not None
        assert (route.proxy_server, route.proxy_username) == (
            "http://proxy.example.com:8080",
            "ada",
        )
        assert route.proxy_password is not None
        assert route.proxy_password.get_secret_value() == "s3cret"
        assert "s3cret" not in repr(route)

    async def test_a_proxy_without_a_password_goes_unsigned(
        self, stored: dict[str, Any], public: None
    ):
        stored["row"] = _row(mode="proxy", proxy_url="http://proxy.example.com:8080")
        route = await _service(stored).resolve(_ctx())
        assert route is not None
        assert route.proxy_username is None and route.proxy_password is None

    async def test_a_hosted_browser_gets_its_key_in_the_query(
        self, stored: dict[str, Any], public: None
    ):
        stored["row"] = _row(
            mode="remote", remote_url="wss://connect.example.com/?region=eu", secret_id=SECRET
        )
        stored["value"] = "key/with+chars"

        route = await _service(stored).resolve(_ctx())

        assert route is not None and route.remote_url is not None
        assert route.remote_url.get_secret_value() == (
            "wss://connect.example.com/?region=eu&apiKey=key%2Fwith%2Bchars"
        )
        assert "key%2Fwith" not in repr(route)

    async def test_a_hosted_browser_with_no_key_is_reached_as_it_is(
        self, stored: dict[str, Any], public: None
    ):
        stored["row"] = _row(mode="remote", remote_url="wss://connect.example.com")
        route = await _service(stored).resolve(_ctx())
        assert route is not None and route.remote_url is not None
        assert route.remote_url.get_secret_value() == "wss://connect.example.com"

    async def test_a_hosted_browser_whose_key_was_removed_refuses_the_run(
        self, stored: dict[str, Any], public: None
    ):
        stored["row"] = _row(
            mode="remote", remote_url="wss://connect.example.com", secret_id=SECRET
        )

        with pytest.raises(BadRequestError, match="removed from the vault"):
            await _service(stored).resolve(_ctx())

    @pytest.mark.security
    async def test_a_name_that_now_points_inside_is_refused_at_run_time(
        self, stored: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ):
        def refuse(url: str, allowed_schemes: frozenset[str]) -> None:
            raise SSRFBlockedError("Blocked: 10.0.0.5 is a private address")

        monkeypatch.setattr(module, "resolve_pinned_url", refuse)
        stored["row"] = _row(mode="proxy", proxy_url="http://proxy.example.com:8080")

        with pytest.raises(BadRequestError, match="private"):
            await _service(stored).resolve(_ctx())

    async def test_a_mode_with_nothing_filled_in_still_gives_the_zone(self, stored: dict[str, Any]):
        stored["row"] = _row(mode="proxy", timezone="Asia/Tokyo")
        assert await _service(stored).resolve(_ctx()) == BrowserRoute(timezone="Asia/Tokyo")


class TestWhatTheBrowserIsTold:
    def test_a_proxy_goes_on_the_context(self):
        assert context_params(None) == {}
        assert context_params(BrowserRoute(timezone="UTC")) == {}
        assert context_params(BrowserRoute(proxy_server="http://p:1")) == {
            "proxyServer": "http://p:1",
            "proxyBypassList": "<-loopback>",
        }

    def test_only_the_proxy_is_given_the_proxy_s_password(self):
        route = BrowserRoute(
            proxy_server="http://p:1", proxy_username="ada", proxy_password=SecretStr("pw")
        )
        proxy = {"requestId": "r1", "authChallenge": {"source": "Proxy"}}
        site = {"requestId": "r2", "authChallenge": {"source": "Server"}}

        assert auth_reply(proxy, route)["authChallengeResponse"] == {
            "response": "ProvideCredentials",
            "username": "ada",
            "password": "pw",
        }
        assert auth_reply(site, route)["authChallengeResponse"] == {"response": "CancelAuth"}
        assert auth_reply(proxy, None)["authChallengeResponse"] == {"response": "CancelAuth"}
        unsigned = BrowserRoute(proxy_server="http://p:1", proxy_username="ada")
        assert auth_reply(proxy, unsigned)["authChallengeResponse"]["password"] == ""

    def test_the_language_rides_on_the_user_agent_override(self):
        desktop = {"userAgent": "Mozilla/5.0 Chrome/155.0.0.0", "product": "Chrome/155.0.0.0"}
        assert user_agent_override(desktop, None) is None
        assert user_agent_override(desktop, "pl-PL") == {
            "userAgent": "Mozilla/5.0 Chrome/155.0.0.0",
            "acceptLanguage": "pl-PL",
        }
        headless = {"userAgent": "HeadlessChrome/156.0.1.2", "product": "HeadlessChrome/156.0.1.2"}
        override = user_agent_override(headless, "de-DE")
        assert override is not None
        assert override["userAgent"] == "Chrome/156.0.1.2"
        assert override["acceptLanguage"] == "de-DE"
