"""Tests for SSRF protection in webhook URL validation.

Covers validate_webhook_url() and _is_ip_blocked() from app.core.sanitize.
"""

from unittest.mock import patch

import pytest

from app.core.sanitize import (
    SSRFBlockedError,
    UrlRefusedError,
    _is_ip_blocked,
    validate_webhook_url,
)

# _is_ip_blocked


class TestIsIpBlocked:
    """Tests for the _is_ip_blocked helper."""

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "0.0.0.0",
            "::1",
            "fe80::1",
            "fc00::1",
            "100.100.100.200",  # CGNAT / Alibaba Cloud metadata
            "100.64.0.1",  # CGNAT range start (RFC 6598)
        ],
    )
    def test_blocked_ips(self, ip: str):
        assert _is_ip_blocked(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "93.184.216.34",  # example.com
            "2606:4700:4700::1111",  # Cloudflare public DNS IPv6
        ],
    )
    def test_allowed_ips(self, ip: str):
        assert _is_ip_blocked(ip) is False

    def test_unparseable_ip_is_blocked(self):
        """If we can't parse it, we block it (fail-closed)."""
        assert _is_ip_blocked("not-an-ip") is True


# validate_webhook_url - scheme validation


class TestSchemeValidation:
    """Blocked schemes must raise SSRFBlockedError."""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://mirror.example.com/pub",
            "gopher://evil.com/",
            "data:text/html,<h1>hi</h1>",
        ],
    )
    def test_blocked_schemes(self, url: str):
        with pytest.raises(SSRFBlockedError):
            validate_webhook_url(url)

    def test_empty_scheme_is_rejected(self):
        with pytest.raises((SSRFBlockedError, ValueError)):
            validate_webhook_url("://example.com/hook")


# validate_webhook_url - IP-literal URLs


class TestDirectIpUrls:
    """URLs with IP-address hostnames (no DNS involved)."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/hook",
            "https://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1:8080/callback",
            "http://192.168.1.1/hook",
            "http://[::1]/hook",
            "http://0.0.0.0/hook",
            "http://100.100.100.200/latest/meta-data/",  # CGNAT / Alibaba metadata
        ],
    )
    def test_private_ip_blocked(self, url: str):
        with pytest.raises(SSRFBlockedError):
            validate_webhook_url(url)

    def test_public_ip_allowed(self):
        """A public IP should pass validation (DNS resolution is skipped)."""
        url = "https://93.184.216.34/webhook"
        assert validate_webhook_url(url) == url


# validate_webhook_url - DNS resolution to private IP


class TestDnsResolution:
    """DNS resolving to a private IP must be blocked."""

    def _mock_getaddrinfo_private(self, *args, **kwargs):
        """Return a private IP for any hostname."""
        return [
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ]

    def _mock_getaddrinfo_public(self, *args, **kwargs):
        """Return a public IP for any hostname."""
        return [
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ]

    def test_dns_resolves_to_private_ip(self):
        with (
            patch("app.core.sanitize.socket.getaddrinfo", self._mock_getaddrinfo_private),
            pytest.raises(SSRFBlockedError),
        ):
            validate_webhook_url("https://evil.attacker.com/hook")

    def test_dns_resolves_to_public_ip(self):
        with patch("app.core.sanitize.socket.getaddrinfo", self._mock_getaddrinfo_public):
            result = validate_webhook_url("https://example.com/webhook")
            assert result == "https://example.com/webhook"


# validate_webhook_url - edge cases


class TestEdgeCases:
    """Edge cases: empty URL, missing hostname, credentials in URL."""

    def test_empty_url(self):
        with pytest.raises((SSRFBlockedError, ValueError)):
            validate_webhook_url("")

    def test_no_hostname(self):
        with pytest.raises(ValueError):
            validate_webhook_url("https:///path")

    def test_url_with_credentials_rejected(self):
        """URLs with userinfo (user:pass@) should be rejected."""
        with pytest.raises(SSRFBlockedError):
            validate_webhook_url("http://user:pass@internal.example.com/hook")

    def test_url_with_username_only_rejected(self):
        with pytest.raises(SSRFBlockedError):
            validate_webhook_url("http://admin@169.254.169.254/")

    def test_allowed_https_url(self):
        """A normal public URL should pass (mock DNS to avoid network calls)."""
        with patch(
            "app.core.sanitize.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        ):
            result = validate_webhook_url("https://example.com/webhook")
            assert result == "https://example.com/webhook"

    def test_allowed_http_url(self):
        """An http:// URL to a public IP should also pass."""
        with patch(
            "app.core.sanitize.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 80))],
        ):
            result = validate_webhook_url("http://example.com/webhook")
            assert result == "http://example.com/webhook"


# validate_webhook_url - what a refusal is allowed to say


class TestRefusalText:
    """A refusal names the host it refused, never the URL.

    Not every URL through here was typed by an operator: `mcp_oauth._send`
    validates each hop of a flow whose endpoints the *remote* server named, and
    a URL carries a key in its query string. The messages reach a user - the
    publish problem `agent_registry._browser_use_problems` builds is one - and
    a log line in every case, so what they may quote is the same question
    `.claude/rules/exceptions-security.md` answers for `details`.
    """

    def test_a_malformed_url_is_refused_without_being_quoted(self):
        with pytest.raises(ValueError) as excinfo:
            validate_webhook_url("https:///reset?token=sh-secret-value")

        assert "sh-secret-value" not in str(excinfo.value)

    def test_an_unparseable_url_is_refused_without_being_quoted(self):
        with pytest.raises(ValueError) as excinfo:
            validate_webhook_url("http://[::1?token=sh-secret-value")

        assert "sh-secret-value" not in str(excinfo.value)

    def test_a_blocked_address_is_refused_by_host_not_by_url(self):
        """The host is what a reader acts on, and carries no query string."""
        with (
            patch(
                "app.core.sanitize.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
            ),
            pytest.raises(SSRFBlockedError) as excinfo,
        ):
            validate_webhook_url("https://oauth.attacker.test/token?client_secret=sh-secret")

        message = str(excinfo.value)
        assert "oauth.attacker.test" in message
        assert "sh-secret" not in message

    def test_a_malformed_port_is_refused_without_quoting_what_was_sent(self):
        """The one refusal the standard library used to write for us.

        `urlsplit` parses the port at attribute access and answers a bad one
        with `Port could not be cast to integer value as '<what you sent>'` -
        so a secret parked where a port belongs came back out through every
        caller that quotes the message (#861).
        """
        with pytest.raises(UrlRefusedError) as excinfo:
            validate_webhook_url("http://example.com:client_secret=sh-secret-value/mcp")

        assert "sh-secret-value" not in str(excinfo.value)


class TestEveryRefusalIsWrittenHere:
    """The type is what makes a message safe to quote to a person.

    `mcp_connection._checked_url` puts it in a 400 and
    `agent_registry._browser_use_problems` puts it in a publish problem, and
    both may do that only because the message was written in this repository
    (`.claude/rules/exceptions-security.md`). A bare `ValueError` from here
    would be the standard library describing what the caller sent.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/hook",
            "https:///reset",
            "http://[::1",
            "http://user:pass@example.com/hook",
            "http://127.0.0.1/hook",
            "http://example.com:not-a-port/hook",
            # A public IP literal, so the port is the only thing wrong with it -
            # and it is read before the IP-literal branch, which used to return
            # this URL as validated for a client that cannot dial it.
            "http://8.8.8.8:not-a-port/hook",
        ],
    )
    def test_a_refused_url_raises_our_own_type(self, url: str):
        with pytest.raises(UrlRefusedError):
            validate_webhook_url(url)


# SSRFBlockedError is a subclass of ValueError


class TestSSRFBlockedError:
    """The dedicated exception type preserves backward compatibility."""

    def test_is_value_error_subclass(self):
        assert issubclass(SSRFBlockedError, ValueError)

    def test_is_a_refusal_written_here(self):
        """What lets `_checked_url` catch the narrow type and still cover
        blocks."""
        assert issubclass(SSRFBlockedError, UrlRefusedError)

    def test_catchable_as_value_error(self):
        with pytest.raises(ValueError):
            raise SSRFBlockedError("blocked")
