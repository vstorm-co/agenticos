"""`MCP_ALLOWED_HOSTS`: the operator's way past the SSRF guard, for a connection's own address.

A server on the deployment's own network - a compose service such as
`postgres-mcp` - resolves to a private address, and `validate_mcp_url` refuses
it with no way past. The setting lists hosts an operator vouched for. A listed
host skips the private-address check and is never resolved. It still has to
pass the form checks: an http(s) scheme, a hostname, no userinfo and a valid port.

The exemption reaches only a caller that asks for it (`honour_allowlist=True`).
OAuth asks only for a connection whose own host is listed: its discovery,
registration and token requests may then reach the listed hosts, still resolved
and pinned, and a public server's flow reaches none. Both are pinned at the end.

DNS is a stub that answers an address inside the network for every name and
records each name it was asked, so a test can tell "accepted" apart from
"resolved, and happened to pass", and nothing here leaves the machine.
"""

import logging
from collections.abc import Awaitable, Callable

import httpx2
import pytest
from mcp.shared.auth import OAuthMetadata

from app.agents import mcp_oauth
from app.agents.mcp import trusted_hosts_for, validate_mcp_url
from app.core.config import settings
from app.core.sanitize import SSRFBlockedError, UrlRefusedError

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_PRIVATE = "10.0.0.9"


@pytest.fixture(autouse=True)
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every name the guard resolved, each answered with an address inside the network."""
    names: list[str] = []

    def fake_getaddrinfo(host: str, port: int, **_kwargs: object) -> list[tuple]:
        names.append(host)
        return [(2, 1, 6, "", (_PRIVATE, port))]

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)
    return names


class TestAListedHost:
    """What the list opens: one host, named exactly, with no DNS asked."""

    @pytest.mark.parametrize("url", ["http://postgres-mcp:8000/mcp", "https://postgres-mcp/mcp"])
    async def test_an_allowlisted_private_host_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch, asked: list[str], url: str
    ) -> None:
        """The case the setting exists for. It is not resolved either: a
        compose service that has not started yet, or a name only the worker's
        network resolves, must not block saving the connection."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["postgres-mcp"])

        assert await validate_mcp_url(url, honour_allowlist=True) == url
        assert asked == []

    async def test_an_accepted_listed_url_is_not_logged(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A server's token can sit in its URL's query string, so letting a
        listed host through must not write the URL anywhere."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["postgres-mcp"])
        url = "http://postgres-mcp:8000/mcp?token=sh-secret"

        with caplog.at_level(logging.DEBUG):
            assert await validate_mcp_url(url, honour_allowlist=True) == url

        assert "sh-secret" not in caplog.text
        assert not any(
            "sh-secret" in str(value)
            for record in caplog.records
            for value in vars(record).values()
        )

    @pytest.mark.parametrize(
        ("entry", "url"),
        [
            ("Postgres-MCP", "http://postgres-mcp:8000/mcp"),
            ("postgres-mcp", "http://POSTGRES-MCP:8000/mcp"),
        ],
    )
    async def test_matching_ignores_case_on_either_side(
        self, monkeypatch: pytest.MonkeyPatch, asked: list[str], entry: str, url: str
    ) -> None:
        """A hostname is case-insensitive, so an entry spelled the way an
        operator types it has to match the URL spelled the way a server's
        README prints it."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", [entry])

        assert await validate_mcp_url(url, honour_allowlist=True) == url
        assert asked == []

    async def test_an_entry_is_trimmed_and_a_blank_one_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whitespace around an entry in a hand-edited `.env` is a typo, not a
        different host, and an empty entry beside it costs the real one nothing."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["  postgres-mcp  ", ""])
        url = "http://postgres-mcp:8000/mcp"

        assert await validate_mcp_url(url, honour_allowlist=True) == url

    async def test_a_blank_entry_opens_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty string is part of every name, so a matcher that reads a
        blank entry as "anything" would open every host as soon as one element
        is empty, such as a templated `["${MCP_HOST}"]` rendered with the
        variable unset."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["", "   "])

        with pytest.raises(SSRFBlockedError):
            await validate_mcp_url("http://postgres-mcp:8000/mcp", honour_allowlist=True)

    @pytest.mark.parametrize("entry", ["fd00::1", "[FD00::1]"])
    async def test_an_ipv6_entry_matches_with_or_without_brackets(
        self, monkeypatch: pytest.MonkeyPatch, entry: str
    ) -> None:
        """A URL needs brackets around an IPv6 address and `urlparse` drops
        them, so an operator copying the address out of the URL must not
        silently list nothing."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", [entry])
        url = "http://[fd00::1]:8000/mcp"

        assert await validate_mcp_url(url, honour_allowlist=True) == url

    async def test_an_ipv4_entry_matches_its_literal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An IP literal is a host too, and is matched as `urlparse` spells it."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["10.0.0.5"])
        url = "http://10.0.0.5:8000/mcp"

        assert await validate_mcp_url(url, honour_allowlist=True) == url


class TestWhatTheListDoesNotOpen:
    """Everything that is not a listed host, spelled exactly, is checked as before."""

    @pytest.mark.parametrize(
        ("url", "host"),
        [
            ("http://10.0.0.9:8000/mcp", "10.0.0.9"),
            ("http://other-mcp:8000/mcp", "other-mcp"),
        ],
    )
    async def test_a_private_host_not_on_the_list_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, url: str, host: str
    ) -> None:
        """Listing one host must not widen the guard for any other, whether
        the address is written out or resolved."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["postgres-mcp"])

        with pytest.raises(SSRFBlockedError) as excinfo:
            await validate_mcp_url(url, honour_allowlist=True)

        assert host in str(excinfo.value)

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://postgres-mcp:8000/mcp",
            "ws://postgres-mcp:8000/mcp",
            "file://postgres-mcp/etc/passwd",
        ],
    )
    async def test_an_allowlisted_host_with_a_non_http_scheme_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        """The list vouches for a host, not for whatever protocol reaches it.
        The scheme check runs before the exemption is looked at."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["postgres-mcp"])

        with pytest.raises(SSRFBlockedError, match="scheme"):
            await validate_mcp_url(url, honour_allowlist=True)

    async def test_an_allowlisted_host_with_userinfo_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Userinfo is refused for the parsing ambiguity it hides, which a
        listed host does not resolve."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["postgres-mcp"])

        with pytest.raises(SSRFBlockedError, match="credentials"):
            await validate_mcp_url("http://user:pass@postgres-mcp:8000/mcp", honour_allowlist=True)

    async def test_an_allowlisted_host_with_a_secret_for_a_port_is_refused_unquoted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The port is read before the exemption, so a listed host still gets
        our own refusal for it, and not the standard library's, which quotes
        what it could not cast (#861)."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["postgres-mcp"])

        with pytest.raises(UrlRefusedError) as excinfo:
            await validate_mcp_url(
                "http://postgres-mcp:client_secret=sh-x/mcp", honour_allowlist=True
            )

        assert "sh-x" not in str(excinfo.value)

    @pytest.mark.parametrize("url", ["http://127.0.0.1:8000/mcp", "http://postgres-mcp:8000/mcp"])
    async def test_an_empty_list_refuses_as_before(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        """The default. A caller that asks for the exemption on a deployment
        that listed nothing gets exactly today's refusals."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", [])

        with pytest.raises(SSRFBlockedError):
            await validate_mcp_url(url, honour_allowlist=True)

    @pytest.mark.parametrize(
        "host",
        [
            # A trailing dot is not folded: an absolute and a relative name can
            # resolve differently through `resolv.conf` search domains.
            "postgres-mcp.",
            # A listed name as a prefix, or inside a longer label, is not that name.
            "postgres-mcp.attacker.test",
            "x-postgres-mcp",
            # No NO_PROXY-style suffix match: a name under a listed one is another host.
            "sub.postgres-mcp",
            # Nor the other way round: part of a listed name is not that name.
            "postgres",
        ],
    )
    async def test_only_an_exact_match_is_exempt(
        self, monkeypatch: pytest.MonkeyPatch, asked: list[str], host: str
    ) -> None:
        """A host that is not a listed name spelled exactly - one containing it,
        one under it, or one it contains - goes through the normal check,
        resolution included, and is refused there."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["postgres-mcp"])

        with pytest.raises(SSRFBlockedError):
            await validate_mcp_url(f"http://{host}:8000/mcp", honour_allowlist=True)

        assert asked == [host]

    @pytest.mark.parametrize(
        ("entry", "url"),
        [
            ("*", "http://postgres-mcp:8000/mcp"),
            ("*-mcp", "http://postgres-mcp:8000/mcp"),
            ("postgres-mc?", "http://postgres-mcp:8000/mcp"),
            # The certificate spelling of "every name under this one" is a name here too.
            ("*.postgres-mcp", "http://sub.postgres-mcp:8000/mcp"),
            (".*", "http://postgres-mcp:8000/mcp"),
            ("10.0.0.0/8", "http://10.0.0.5:8000/mcp"),
            # A leading dot is the cookie and NO_PROXY spelling of "this domain and
            # everything under it". Here it is a name, so it opens neither.
            (".postgres-mcp", "http://sub.postgres-mcp:8000/mcp"),
            (".postgres-mcp", "http://postgres-mcp:8000/mcp"),
            # An absolute entry is not its relative name: no dot is folded off either side.
            ("postgres-mcp.", "http://postgres-mcp:8000/mcp"),
        ],
    )
    async def test_an_entry_is_a_name_not_a_pattern(
        self, monkeypatch: pytest.MonkeyPatch, entry: str, url: str
    ) -> None:
        """A glob or a range would open far more than the operator meant, the
        metadata address included. An entry that looks like one matches only
        a host spelled exactly that way, which none is."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", [entry])

        with pytest.raises(SSRFBlockedError):
            await validate_mcp_url(url, honour_allowlist=True)

    async def test_an_unparsable_url_at_a_listed_host_is_a_form_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_checked_url` turns only `UrlRefusedError` into a 400, so the list is
        looked up after the URL is parsed by the guard, never by parsing it
        first somewhere the guard's refusal does not reach."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["::1"])

        with pytest.raises(UrlRefusedError, match="could not be parsed"):
            await validate_mcp_url("http://[::1/mcp", honour_allowlist=True)

    async def test_an_ipv6_entry_is_compared_as_written(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`fd00:0::1` and `fd00::1` are one address but two spellings, and
        the match is textual: a mismatch falls through to the normal check,
        which is the fail-closed direction."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["fd00:0::1"])

        with pytest.raises(SSRFBlockedError):
            await validate_mcp_url("http://[fd00::1]:8000/mcp", honour_allowlist=True)

    @pytest.mark.parametrize("url", ["http://postgres-mcp:8000/mcp", "http://10.0.0.5:8000/mcp"])
    async def test_without_the_flag_the_list_is_not_read(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        """The strict default is what keeps a public server's consent URL and
        the catalog audit refused for a listed host: neither passes the flag,
        and a new caller that forgets it fails closed."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["postgres-mcp", "10.0.0.5"])

        with pytest.raises(SSRFBlockedError):
            await validate_mcp_url(url)


class _OAuthServers:
    """Servers that sign people in, keyed by the `Host` each request names.

    Every host serves the same documents: protected-resource metadata naming
    `authorization_server`, authorization-server metadata whose three endpoints
    sit on that server, a registration that answers a client, and a token
    endpoint that answers a token. `seen` records the host and path of every
    request that reached the wire, so a test can tell "refused" apart from
    "sent, and answered badly".
    """

    def __init__(self, authorization_server: str, *, consent_at: str | None = None) -> None:
        self.authorization_server = authorization_server
        self.consent_at = consent_at or f"{authorization_server}/authorize"
        self.seen: list[tuple[str, str]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        host = request.headers["host"]
        path = request.url.path
        self.seen.append((host, path))
        issuer = self.authorization_server
        if path.startswith("/.well-known/oauth-protected-resource"):
            return httpx2.Response(
                200,
                json={"resource": f"http://{host}/mcp", "authorization_servers": [issuer]},
            )
        if path.startswith("/.well-known/oauth-authorization-server"):
            return httpx2.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": self.consent_at,
                    "token_endpoint": f"{issuer}/token",
                    "registration_endpoint": f"{issuer}/register",
                    "response_types_supported": ["code"],
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if path == "/register":
            return httpx2.Response(
                201,
                json={"client_id": "cid", "redirect_uris": ["https://app.example.com/cb"]},
            )
        if path == "/token":
            return httpx2.Response(
                200,
                json={"access_token": "at", "token_type": "Bearer", "refresh_token": "rt"},
            )
        return httpx2.Response(401)

    def serve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Point every client the flow opens at these servers instead of a network."""
        real = mcp_oauth._client
        monkeypatch.setattr(
            mcp_oauth, "_client", lambda **kw: real(httpx2.MockTransport(self), **kw)
        )


async def _exchange(token_endpoint: str, *, server_url: str) -> None:
    await mcp_oauth.exchange_code(
        token_endpoint=token_endpoint,
        client_id="cid",
        client_secret=None,
        code="code",
        code_verifier="verifier",
        redirect_uri="https://app.example.com/cb",
        resource=server_url,
        server_url=server_url,
    )


async def _refresh(token_endpoint: str, *, server_url: str) -> None:
    await mcp_oauth.refresh_tokens(
        token_endpoint=token_endpoint,
        client_id="cid",
        client_secret=None,
        refresh_token="rt",
        resource=server_url,
        scope=None,
        server_url=server_url,
    )


class TestOAuthFromAListedHost:
    """A server on the deployment's network that signs people in itself: its
    metadata, registration and token endpoints are on the listed host too, so
    the flow for a connection to it may reach the listed hosts."""

    _SERVER = "http://mcp.internal:8000/mcp"

    async def test_the_whole_flow_reaches_the_listed_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.internal"])
        servers = _OAuthServers("http://mcp.internal:8000")
        servers.serve(monkeypatch)

        server = await mcp_oauth.discover(self._SERVER)
        assert server.trusted_hosts == {"mcp.internal"}
        assert server.authorization_endpoint == "http://mcp.internal:8000/authorize"

        assert await mcp_oauth.register_client(server, "https://app.example.com/cb") == (
            "cid",
            None,
        )
        await _exchange(server.token_endpoint, server_url=self._SERVER)
        await _refresh(server.token_endpoint, server_url=self._SERVER)

        paths = [path for host, path in servers.seen if host == "mcp.internal:8000"]
        assert paths[-3:] == ["/register", "/token", "/token"]
        assert {host for host, _path in servers.seen} == {"mcp.internal:8000"}

    async def test_it_may_sign_in_at_another_listed_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An identity provider on the same network under its own name. A member
        could save a connection to either host, so reaching the second opens
        nothing the list did not."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.internal", "sso.internal"])
        servers = _OAuthServers("http://sso.internal")
        servers.serve(monkeypatch)

        server = await mcp_oauth.discover(self._SERVER)
        await _exchange(server.token_endpoint, server_url=self._SERVER)

        assert ("sso.internal", "/token") in servers.seen

    async def test_it_may_not_reach_a_private_host_nobody_listed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The list widens the flow to the listed hosts, not to the network."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.internal"])
        servers = _OAuthServers("http://sso.internal")
        servers.serve(monkeypatch)

        with pytest.raises(mcp_oauth.OAuthError, match="did not advertise OAuth metadata"):
            await mcp_oauth.discover(self._SERVER)

        assert not any(host == "sso.internal" for host, _path in servers.seen)

    @pytest.mark.parametrize("answer", ["127.0.0.1", "169.254.169.254", "100.100.100.200", "::1"])
    async def test_a_listed_name_answering_what_the_list_refuses_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, answer: str
    ) -> None:
        """Loopback, link-local and metadata addresses are refused as entries at
        startup, so a DNS answer must not open them either: the list is never a
        way to the deployment itself or to the instance's credentials."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.internal"])
        family = 10 if ":" in answer else 2
        monkeypatch.setattr(
            "app.core.sanitize.socket.getaddrinfo",
            lambda _host, port, **_kw: [(family, 1, 6, "", (answer, port))],
        )
        servers = _OAuthServers("http://mcp.internal:8000")
        servers.serve(monkeypatch)

        with pytest.raises(mcp_oauth.OAuthError, match="blocked address"):
            await _exchange("http://mcp.internal:8000/token", server_url=self._SERVER)

        assert servers.seen == []

    async def test_a_consent_page_at_a_listed_name_answering_loopback_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The consent URL is checked rather than fetched, but by the hops' own
        policy: a listed name is resolved there too, so it cannot send somebody's
        browser to an address the list may never name."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.internal", "login.internal"])

        def resolve(host: str, port: int, **_kwargs: object) -> list[tuple]:
            answer = "127.0.0.1" if host == "login.internal" else _PRIVATE
            return [(2, 1, 6, "", (answer, port))]

        monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", resolve)
        servers = _OAuthServers(
            "http://mcp.internal:8000", consent_at="http://login.internal/authorize"
        )
        servers.serve(monkeypatch)

        with pytest.raises(mcp_oauth.OAuthError, match="blocked address"):
            await mcp_oauth.discover(self._SERVER)

    async def test_a_listed_name_outside_ascii_is_matched_as_it_is_sent(
        self, monkeypatch: pytest.MonkeyPatch, asked: list[str]
    ) -> None:
        """httpx2 IDNA-encodes the host before the pinned client checks it, so
        a listed `täst.internal` is asked for as `xn--tst-qla.internal`."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["täst.internal"])
        server_url = "http://täst.internal:8000/mcp"
        servers = _OAuthServers("http://täst.internal:8000")
        servers.serve(monkeypatch)

        server = await mcp_oauth.discover(server_url)
        await _exchange(server.token_endpoint, server_url=server_url)

        assert server.trusted_hosts == {"täst.internal", "xn--tst-qla.internal"}
        assert "xn--tst-qla.internal" in asked
        assert ("xn--tst-qla.internal:8000", "/token") in servers.seen

    @pytest.mark.parametrize(
        "server_url",
        ["http://[mcp.internal/mcp", "http://💩.internal/mcp"],
        ids=["urlparse-cannot-read", "httpx2-cannot-encode"],
    )
    async def test_a_url_that_cannot_be_read_or_sent_trusts_nothing(
        self, monkeypatch: pytest.MonkeyPatch, server_url: str
    ) -> None:
        """A host the flow could never reach as written earns no exemption; the
        guard that checks the URL next writes the refusal."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.internal"])

        assert trusted_hosts_for(server_url) == frozenset()

    async def test_a_host_taken_off_the_list_is_no_longer_refreshed_at(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The list is read at every refresh, not frozen into the stored grant."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", [])
        servers = _OAuthServers("http://mcp.internal:8000")
        servers.serve(monkeypatch)

        with pytest.raises(mcp_oauth.OAuthError, match="blocked address"):
            await _refresh("http://mcp.internal:8000/token", server_url=self._SERVER)

        assert servers.seen == []


class TestOAuthFromAPublicServer:
    """A public server's metadata names its own endpoints, and listing a host
    must not let it aim any of them there: a flow that did not begin at a
    listed host reaches none."""

    _SERVER = "https://93.184.216.34/mcp"

    async def test_its_metadata_cannot_name_a_listed_authorization_server(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.internal"])
        servers = _OAuthServers("http://mcp.internal:8000")
        servers.serve(monkeypatch)

        with pytest.raises(mcp_oauth.OAuthError, match="did not advertise OAuth metadata"):
            await mcp_oauth.discover(self._SERVER)

        assert not any(host.startswith("mcp.internal") for host, _path in servers.seen)

    async def test_a_consent_url_at_a_listed_private_host_is_still_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The authorization endpoint is named by the remote server and opened
        by somebody's browser, so it is checked rather than fetched. A public
        server must not be able to point a consent redirect at a listed host."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["10.0.0.5"])

        def handler(request: httpx2.Request) -> httpx2.Response:
            if request.url.path == "/.well-known/oauth-protected-resource":
                return httpx2.Response(
                    200,
                    json={
                        "resource": self._SERVER,
                        "authorization_servers": ["https://93.184.216.35"],
                    },
                )
            if request.url.path == "/.well-known/oauth-authorization-server":
                return httpx2.Response(
                    200,
                    json={
                        "issuer": "https://93.184.216.35",
                        "authorization_endpoint": "https://10.0.0.5/authorize",
                        "token_endpoint": "https://93.184.216.35/token",
                        "response_types_supported": ["code"],
                    },
                )
            return httpx2.Response(404, json={})

        real = mcp_oauth._client
        monkeypatch.setattr(
            mcp_oauth, "_client", lambda **kw: real(httpx2.MockTransport(handler), **kw)
        )
        with pytest.raises(mcp_oauth.OAuthError, match="blocked address"):
            await mcp_oauth.discover(self._SERVER)

    async def test_it_cannot_name_a_listed_registration_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.internal"])
        servers = _OAuthServers("http://mcp.internal:8000")
        servers.serve(monkeypatch)
        server = mcp_oauth.DiscoveredServer(
            authorization_endpoint="https://93.184.216.34/authorize",
            token_endpoint="https://93.184.216.34/token",
            registration_endpoint="http://mcp.internal:8000/register",
            resource=self._SERVER,
            scope=None,
            metadata=OAuthMetadata.model_validate(
                {
                    "issuer": "https://93.184.216.34",
                    "authorization_endpoint": "https://93.184.216.34/authorize",
                    "token_endpoint": "https://93.184.216.34/token",
                    "registration_endpoint": "http://mcp.internal:8000/register",
                }
            ),
            trusted_hosts=trusted_hosts_for(self._SERVER),
        )

        with pytest.raises(mcp_oauth.OAuthError, match="blocked address"):
            await mcp_oauth.register_client(server, "https://app.example.com/cb")

        assert servers.seen == []

    @pytest.mark.parametrize("step", [_exchange, _refresh], ids=["exchange", "refresh"])
    async def test_it_cannot_name_a_listed_token_endpoint(
        self, monkeypatch: pytest.MonkeyPatch, step: Callable[..., Awaitable[None]]
    ) -> None:
        """The token endpoint comes from the server's metadata and is stored
        with the grant, so a refresh is checked against the connection's own
        address just as the first exchange is."""
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.internal"])
        servers = _OAuthServers("http://mcp.internal:8000")
        servers.serve(monkeypatch)

        with pytest.raises(mcp_oauth.OAuthError, match="blocked address"):
            await step("http://mcp.internal:8000/token", server_url=self._SERVER)

        assert servers.seen == []
