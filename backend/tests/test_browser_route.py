"""#2130: how one agent's browses reach the web - its binding's settings, and the route a run gets."""

from typing import Any

import pytest
from pydantic import SecretStr

from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, get
from app.agents.capabilities.browser_use import WebBrowserConfig, connection_problems
from app.agents.capabilities.browser_use import _route as module
from app.agents.capabilities.browser_use._page import (
    auth_reply,
    context_params,
    user_agent_override,
)
from app.agents.capabilities.browser_use._route import (
    BrowserRoute,
    check_address,
    recheck,
    route_for,
)
from app.core.config import settings
from app.core.sanitize import SSRFBlockedError, UrlRefusedError
from app.core.secret_kinds import ApiKeySecret

pytestmark = pytest.mark.anyio


@pytest.fixture
def public(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every name resolves to a public address; only `browser` is on the operator's list."""
    resolved: list[str] = []

    def resolve(url: str, allowed_schemes: frozenset[str]) -> None:
        resolved.append(url)

    monkeypatch.setattr(module, "resolve_pinned_url", resolve)
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    return resolved


def _route(**fields: Any) -> BrowserRoute | None:
    values: dict[str, Any] = {
        "connection": "built_in",
        "proxy_url": "",
        "hosted_url": "",
        "hosted_key_param": "apiKey",
        "timezone": None,
        "locale": None,
        "credential": None,
    }
    return route_for(**(values | fields))


def _built(config: dict[str, Any], key: str | None = None) -> Any:
    """The capability as the registry builds it, with the binding's vault entry."""
    definition = get("browser_use")
    return definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="browser_use", config=config),
            config=definition.validate_config(config),
            secret=None if key is None else ApiKeySecret(api_key=SecretStr(key)),
        )
    )


class TestAnAddressIsChecked:
    async def test_a_public_proxy_with_a_port_is_accepted(self, public: list[str]):
        await check_address("http://proxy.example.com:8080", kind="proxy")
        await check_address("socks5://proxy.example.com:1080", kind="proxy")
        assert public == ["http://proxy.example.com:8080", "socks5://proxy.example.com:1080"]

    @pytest.mark.parametrize(
        ("url", "reason"),
        [
            ("ftp://proxy.example.com:21", "Use a http, https, socks5 address"),
            ("http://ada:pw@proxy.example.com:8080", "Keep the credentials out"),
            ("http://proxy.example.com:port", "The port is not a number"),
            ("http://proxy.example.com", "needs its port"),
        ],
    )
    async def test_a_proxy_address_that_cannot_be_used_says_why(
        self, public: list[str], url: str, reason: str
    ):
        with pytest.raises(UrlRefusedError, match=reason):
            await check_address(url, kind="proxy")
        assert public == []

    async def test_an_address_inside_the_network_is_refused(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", [])
        with pytest.raises(SSRFBlockedError):
            await check_address("http://10.0.0.5:3128", kind="proxy")

    async def test_a_host_the_operator_named_may_be_inside_and_in_the_clear(
        self, public: list[str]
    ):
        await check_address("ws://browser:9222/devtools", kind="hosted")
        assert public == []

    async def test_a_hosted_browser_elsewhere_is_reached_over_tls(self, public: list[str]):
        await check_address("wss://connect.example.com", kind="hosted")
        with pytest.raises(UrlRefusedError, match="Use a wss address"):
            await check_address("ws://connect.example.com", kind="hosted")

    async def test_a_name_that_now_points_inside_is_refused_as_a_browse_starts(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", [])
        hosted = _route(connection="hosted", hosted_url="wss://10.0.0.9", credential="k")
        assert hosted is not None
        with pytest.raises(SSRFBlockedError):
            await recheck(hosted)
        proxy = _route(connection="proxy", proxy_url="http://10.0.0.5:3128")
        assert proxy is not None
        with pytest.raises(SSRFBlockedError):
            await recheck(proxy)

    @pytest.mark.security
    async def test_a_proxy_is_handed_on_at_the_address_it_was_checked_at(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Codex on #2062: the browser resolved the proxy's name again, and a name
        that answered a public address here could answer an internal one there."""
        from app.core.sanitize import PinnedAddress

        monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", [])
        monkeypatch.setattr(
            module,
            "resolve_pinned_url",
            lambda url, allowed_schemes: PinnedAddress(
                hostname="proxy.example.com", port=8080, ips=("203.0.113.9", "2001:db8::1")
            ),
        )

        plain = await recheck(BrowserRoute(proxy_server="http://proxy.example.com:8080"))
        socks = await recheck(BrowserRoute(proxy_server="socks5://proxy.example.com:8080"))
        tls = BrowserRoute(proxy_server="https://proxy.example.com:8080")

        assert plain.proxy_server == "http://203.0.113.9:8080"
        assert socks.proxy_server == "socks5://203.0.113.9:8080"
        # Its certificate is issued for the name, so the name stays.
        assert (await recheck(tls)) == tls

    async def test_an_ipv6_proxy_address_is_bracketed(self, monkeypatch: pytest.MonkeyPatch):
        from app.core.sanitize import PinnedAddress

        monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", [])
        monkeypatch.setattr(
            module,
            "resolve_pinned_url",
            lambda url, allowed_schemes: PinnedAddress(
                hostname="proxy.example.com", port=3128, ips=("2001:db8::1",)
            ),
        )

        pinned = await recheck(BrowserRoute(proxy_server="http://proxy.example.com:3128"))

        assert pinned.proxy_server == "http://[2001:db8::1]:3128"

    async def test_the_hosted_key_is_not_what_gets_checked(self, public: list[str]):
        route = _route(connection="hosted", hosted_url="wss://h.example.com", credential="k")
        assert route is not None
        await recheck(route)
        assert public == ["wss://h.example.com"]


class TestTheBindingsSettings:
    def test_the_built_in_browser_has_nothing_to_say(self):
        assert connection_problems(WebBrowserConfig(), has_secret=False) == []

    @pytest.mark.parametrize(
        ("config", "has_secret", "problem"),
        [
            ({"connection": "proxy"}, False, "Say which proxy"),
            ({"connection": "proxy", "proxy_url": "http://p.example.com"}, False, "needs its port"),
            (
                {"connection": "proxy", "proxy_url": "socks5://p.example.com:1080"},
                True,
                "cannot sign in to a SOCKS proxy",
            ),
            ({"connection": "hosted"}, True, "Say where the hosted browser is"),
            ({"connection": "hosted", "hosted_url": "https://h.example.com"}, True, "wss"),
            ({"timezone": "Mars/Olympus"}, False, "not an IANA time zone"),
        ],
    )
    def test_what_cannot_work_is_refused_in_words(
        self, config: dict[str, Any], has_secret: bool, problem: str
    ):
        problems = connection_problems(WebBrowserConfig(**config), has_secret=has_secret)
        assert len(problems) == 1
        assert problem in problems[0]

    def test_a_socks_proxy_without_a_password_is_fine(self):
        config = WebBrowserConfig(connection="proxy", proxy_url="socks5://p.example.com:1080")
        assert connection_problems(config, has_secret=False) == []

    def test_an_emptied_field_means_none(self):
        config = WebBrowserConfig(timezone="", locale="")
        assert (config.timezone, config.locale) == (None, None)

    def test_a_hosted_browser_needs_a_key_and_a_proxy_may_have_one(self):
        definition = get("browser_use")
        hosted = definition.validate_config({"connection": "hosted"})
        proxy = definition.validate_config({"connection": "proxy"})
        assert definition.needs_secret(hosted)
        assert not definition.needs_secret(proxy)
        assert not definition.needs_secret(definition.validate_config({}))


class TestTheRouteARunGets:
    def test_the_default_says_nothing(self):
        assert _route() is None
        assert _built({"cdp_url": "http://browser:9222"}).route is None

    def test_the_built_in_browser_can_still_say_where_it_is(self):
        assert _route(timezone="Europe/Warsaw", locale="pl-PL") == BrowserRoute(
            timezone="Europe/Warsaw", locale="pl-PL"
        )

    def test_a_proxy_carries_its_credentials_masked(self):
        built = _built(
            {"connection": "proxy", "proxy_url": "http://p.example.com:8080"}, key="ada:s3cret"
        )
        route = built.route
        assert route.proxy_server == "http://p.example.com:8080"
        assert route.proxy_username == "ada"
        assert route.proxy_password.get_secret_value() == "s3cret"
        assert "s3cret" not in repr(route)

    def test_a_proxy_without_a_password_goes_unsigned(self):
        route = _route(connection="proxy", proxy_url="http://p.example.com:8080")
        assert route == BrowserRoute(proxy_server="http://p.example.com:8080")

    def test_a_hosted_browser_gets_its_key_in_the_query(self):
        built = _built(
            {
                "connection": "hosted",
                "hosted_url": "wss://h.example.com/connect?region=eu",
                "hosted_key_param": "token",
            },
            key="key&with&amp",
        )
        route = built.route
        assert route.remote_url.get_secret_value() == (
            "wss://h.example.com/connect?region=eu&token=key%26with%26amp"
        )
        assert route.remote_address == "wss://h.example.com/connect?region=eu"

    def test_a_hosted_browser_with_no_key_is_reached_as_it_is(self):
        route = _route(connection="hosted", hosted_url="wss://h.example.com")
        assert route is not None
        assert route.remote_url is not None
        assert route.remote_url.get_secret_value() == "wss://h.example.com"

    def test_a_mode_with_nothing_filled_in_still_gives_the_zone(self):
        assert _route(connection="proxy", timezone="Asia/Tokyo") == BrowserRoute(
            timezone="Asia/Tokyo"
        )


class TestWhatTheBrowserIsTold:
    def test_without_any_proxy_the_context_has_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "BROWSER_EGRESS_PROXY", "")
        assert context_params(None) == {}

    def test_the_deployment_s_egress_proxy_is_the_default_but_not_for_a_hosted_browser(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "BROWSER_EGRESS_PROXY", "http://browser-egress:3128")
        egress = {"proxyServer": "http://browser-egress:3128", "proxyBypassList": "<-loopback>"}

        assert context_params(None) == egress
        assert context_params(BrowserRoute(timezone="UTC")) == egress
        # The organization's own proxy wins, and a hosted browser cannot reach ours.
        assert (
            context_params(BrowserRoute(proxy_server="http://p:1"))["proxyServer"] == "http://p:1"
        )
        assert context_params(None, hosted=True) == {}

    def test_a_proxy_goes_on_the_context(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "BROWSER_EGRESS_PROXY", "")
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
