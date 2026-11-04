"""The private-network allowlist: its entry forms, its matching and the origin rule.

DNS is a stub that maps names to answer lists and records every name it was
asked, so nothing here leaves the machine.
"""

import logging
import socket
from collections.abc import Callable

import pytest

from app.core.config import settings
from app.core.sanitize import (
    PrivateAllowlistEntryError,
    SSRFBlockedError,
    allowlist_for,
    deployment_allowlist,
    mcp_allowlist,
    parse_private_allowlist,
    resolve_pinned_url,
    validate_webhook_url,
    wire_spelling,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, list[str]]], list[str]]:
    """Install answers per name; a name not given does not resolve. Returns the names asked."""
    asked: list[str] = []

    def install(answers: dict[str, list[str]]) -> list[str]:
        def fake_getaddrinfo(host: str, port: int, **_kwargs: object) -> list[tuple]:
            asked.append(host)
            if host not in answers:
                raise socket.gaierror("no such name")
            return [(2, 1, 6, "", (ip, port)) for ip in answers[host]]

        monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)
        return asked

    return install


class TestParsing:
    def test_a_suffix_admits_a_subdomain_but_not_the_apex_or_a_lookalike(self) -> None:
        listed = parse_private_allowlist([".corp.example"])

        assert listed.admits_name("mcp.corp.example")
        assert listed.admits_name("a.b.corp.example")
        assert not listed.admits_name("corp.example")
        assert not listed.admits_name("evilcorp.example")

    def test_matching_ignores_case_and_one_trailing_dot(self) -> None:
        listed = parse_private_allowlist(["Wiki.Corp.Example."])

        assert listed.admits_name("wiki.corp.example")
        assert listed.admits_name("WIKI.corp.example.")

    def test_an_ip_entry_is_a_one_address_network(self) -> None:
        v6 = parse_private_allowlist(["fd00:0::1"])
        bracketed = parse_private_allowlist(["[FD00::1]"])
        v4 = parse_private_allowlist(["10.0.0.5"])

        assert v6.admits_address("x", "fd00::1")
        assert bracketed.admits_address("x", "fd00::1")
        assert v4.admits_address("x", "10.0.0.5")
        assert not v4.admits_address("x", "10.0.0.6")

    def test_a_cidr_entry_admits_addresses_inside_it_only(self) -> None:
        listed = parse_private_allowlist(["10.1.2.0/24"])
        host_bits = parse_private_allowlist(["10.1.2.5/24"])

        assert listed.admits_address("x", "10.1.2.5")
        assert not listed.admits_address("x", "10.1.3.5")
        assert host_bits.networks == listed.networks

    def test_blank_entries_open_nothing(self) -> None:
        listed = parse_private_allowlist(["", "   "])

        assert bool(listed) is False
        assert not listed.admits_name("")
        assert not listed.admits_address("x", "10.0.0.5")

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "169.254.169.254",
            "::ffff:127.0.0.1",
            "100.100.100.200",
            "fd00:ec2::254",
            "64:ff9b::a9fe:a9fe",
            "64:ff9b::7f00:1",
            "64:ff9b::6464:64c8",
            "2002:a9fe:a9fe::1",
            "2002:7f00:1::1",
        ],
    )
    def test_a_listed_name_never_admits_a_never_reachable_address(self, ip: str) -> None:
        listed = parse_private_allowlist([".corp.example"])

        assert not listed.admits_address("x.corp.example", ip)

    def test_an_address_embedding_a_private_one_is_listed_by_its_embedding_network(self) -> None:
        listed = parse_private_allowlist(["64:ff9b::a00:0/104", "2002:c0a8::/32"])

        assert listed.admits_address("x", "64:ff9b::a00:5")
        assert listed.admits_address("x", "2002:c0a8:1::1")

    def test_an_entry_outside_ascii_matches_its_wire_spelling(self) -> None:
        listed = parse_private_allowlist([".täst.example"])

        assert listed.admits_name(f"sub.{wire_spelling('täst.example')}")
        assert listed.admits_name("sub.täst.example")

    def test_a_listed_name_admits_any_address_it_answers_that_is_reachable(self) -> None:
        listed = parse_private_allowlist([".corp.example"])

        assert listed.admits_address("x.corp.example", "10.9.9.9")

    def test_an_ipv4_mapped_address_is_read_as_its_ipv4_address(self) -> None:
        listed = parse_private_allowlist(["10.1.2.0/24"])

        assert listed.admits_address("x", "::ffff:10.1.2.5")
        assert not listed.admits_address("x", "::ffff:10.1.3.5")

    def test_an_entry_that_looks_numeric_but_is_not_an_address_is_a_name(self) -> None:
        listed = parse_private_allowlist(["0db"])

        assert listed.names == frozenset({"0db"})
        assert listed.admits_name("0db")

    def test_a_long_ipv6_prefix_that_is_not_ipv4_mapped_stays_ipv6(self) -> None:
        listed = parse_private_allowlist(["fd00::/112"])

        assert listed.admits_address("x", "fd00::5")
        assert not listed.admits_address("x", "fd00::1:5")

    def test_the_entries_keep_the_configured_text_trimmed(self) -> None:
        listed = parse_private_allowlist([" wiki ", "", "10.0.0.0/24"])

        assert listed.entries == ("wiki", "10.0.0.0/24")

    @pytest.mark.parametrize(
        "entry",
        [
            "169.254.169.254",
            "metadata.google.internal",
            "localhost",
            "app.localhost",
            ".localhost",
            ".internal",
            ".google.internal",
            "127.0.0.0/8",
            "10.0.0.0/0",
            "0.0.0.0/0",
            "169.254.0.0/16",
            "fe80::/10",
            "::1",
            "100.64.0.0/10",
            "fd00::/8",
            "2852039166",
            "::ffff:169.254.169.254",
            "::ffff:127.0.0.0/104",
            "::ffff:7f00:0/104",
            "::ffff:a9fe:0/112",
            "::ffff:0:0/96",
            "::ffff:6464:64c8/128",
            "64:ff9b::/96",
            "64:ff9b::a9fe:0/112",
            "64:ff9b::7f00:0/104",
            "2002::/16",
            "2002:7f00::/24",
            "2002:a9fe:a9fe::/48",
            "http://wiki",
            "wiki:8080",
            "*.corp.example",
            "a..b",
            ".",
            "10.0.0.0/33",
        ],
    )
    def test_each_refused_entry_names_itself(self, entry: str) -> None:
        with pytest.raises(PrivateAllowlistEntryError) as raised:
            parse_private_allowlist([entry])

        assert raised.value.entry == entry
        assert raised.value.reason


class TestTheDeploymentLists:
    def test_the_deployment_list_reads_the_setting_on_every_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", ["10.1.2.0/24", "wiki"])

        listed = deployment_allowlist()

        assert listed.admits_name("wiki")
        assert listed.admits_address("x", "10.1.2.9")

    def test_only_the_mcp_list_reads_mcp_allowed_hosts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", ["10.1.2.0/24"])
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["postgres-mcp"])

        assert not deployment_allowlist().admits_name("postgres-mcp")
        assert mcp_allowlist().admits_name("postgres-mcp")
        assert mcp_allowlist().admits_address("x", "10.1.2.9")


class TestAllowlistFor:
    @pytest.fixture(autouse=True)
    def listed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", ["wiki", "10.1.2.0/24"])

    def test_a_chain_starting_at_a_listed_name_gets_the_list(
        self, fake_dns: Callable[[dict[str, list[str]]], list[str]]
    ) -> None:
        asked = fake_dns({})

        assert allowlist_for("http://wiki/page") == deployment_allowlist()
        assert asked == []

    def test_a_chain_starting_at_an_address_inside_a_network_gets_the_list(
        self, fake_dns: Callable[[dict[str, list[str]]], list[str]]
    ) -> None:
        fake_dns({"svc.local": ["10.1.2.7"]})

        assert allowlist_for("http://10.1.2.7/") == deployment_allowlist()
        assert allowlist_for("http://svc.local/") == deployment_allowlist()

    def test_a_chain_starting_at_a_public_host_gets_nothing(
        self, fake_dns: Callable[[dict[str, list[str]]], list[str]]
    ) -> None:
        fake_dns({"example.org": ["93.184.216.34"]})

        assert not allowlist_for("https://example.org/")

    def test_a_chain_starting_at_a_host_answering_public_and_admitted_gets_the_list(
        self, fake_dns: Callable[[dict[str, list[str]]], list[str]]
    ) -> None:
        fake_dns({"split.local": ["93.184.216.34", "10.1.2.7"]})

        assert allowlist_for("http://split.local/") == deployment_allowlist()

    def test_a_chain_starting_at_an_unlisted_private_host_gets_nothing(
        self, fake_dns: Callable[[dict[str, list[str]]], list[str]]
    ) -> None:
        fake_dns({"other.local": ["10.9.9.9"], "mixed.local": ["10.1.2.7", "10.9.9.9"]})

        assert not allowlist_for("http://other.local/")
        assert not allowlist_for("http://mixed.local/")

    def test_an_unparsable_or_unresolvable_origin_gets_nothing(
        self, fake_dns: Callable[[dict[str, list[str]]], list[str]]
    ) -> None:
        fake_dns({})

        assert not allowlist_for("http://a..b/")
        assert not allowlist_for("http://nowhere.local/")

    def test_an_explicit_list_replaces_the_deployment_list(
        self, fake_dns: Callable[[dict[str, list[str]]], list[str]]
    ) -> None:
        fake_dns({})
        explicit = parse_private_allowlist(["postgres-mcp"])

        assert allowlist_for("http://postgres-mcp/", explicit) == explicit
        assert not allowlist_for("http://wiki/", explicit)

    def test_an_empty_deployment_list_gives_nothing_without_resolving(
        self, monkeypatch: pytest.MonkeyPatch, fake_dns: Callable[[dict[str, list[str]]], list[str]]
    ) -> None:
        monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", [])
        asked = fake_dns({"wiki": ["10.1.2.7"]})

        assert not allowlist_for("http://wiki/")
        assert asked == []


_Dns = Callable[[dict[str, list[str]]], list[str]]


class TestTheGuard:
    @pytest.mark.parametrize("address", ["10.0.0.5", "192.168.1.1", "100.64.0.1"])
    def test_an_empty_list_refuses_every_private_answer_as_before(
        self, fake_dns: _Dns, address: str
    ) -> None:
        fake_dns({"wiki": [address]})

        with pytest.raises(SSRFBlockedError):
            resolve_pinned_url("http://wiki/x")
        with pytest.raises(SSRFBlockedError):
            resolve_pinned_url(f"http://{address}/x")

    def test_a_name_resolving_inside_the_range_is_pinned_there(self, fake_dns: _Dns) -> None:
        fake_dns({"wiki": ["10.1.2.5"]})
        listed = parse_private_allowlist(["10.1.2.0/24"])

        pinned = resolve_pinned_url("http://wiki/x", private_allowlist=listed)

        assert pinned.ips == ("10.1.2.5",)
        assert pinned.hostname == "wiki"

    def test_a_name_resolving_outside_the_range_is_refused(self, fake_dns: _Dns) -> None:
        fake_dns({"wiki": ["10.1.3.5"]})
        listed = parse_private_allowlist(["10.1.2.0/24"])

        with pytest.raises(SSRFBlockedError):
            resolve_pinned_url("http://wiki/x", private_allowlist=listed)

    def test_a_name_answering_public_and_an_unlisted_private_address_is_refused(
        self, fake_dns: _Dns
    ) -> None:
        fake_dns({"wiki": ["93.184.216.34", "10.1.3.5"]})
        listed = parse_private_allowlist(["10.1.2.0/24"])

        with pytest.raises(SSRFBlockedError):
            resolve_pinned_url("http://wiki/x", private_allowlist=listed)

    def test_a_name_answering_public_and_a_listed_private_address_pins_both(
        self, fake_dns: _Dns
    ) -> None:
        fake_dns({"wiki": ["93.184.216.34", "10.1.2.5"]})
        listed = parse_private_allowlist(["10.1.2.0/24"])

        pinned = resolve_pinned_url("http://wiki/x", private_allowlist=listed)

        assert pinned.ips == ("93.184.216.34", "10.1.2.5")

    def test_a_suffix_admits_its_subdomain_at_a_private_address(self, fake_dns: _Dns) -> None:
        fake_dns({"mcp.corp.example": ["10.9.9.9"]})
        listed = parse_private_allowlist([".corp.example"])

        pinned = resolve_pinned_url("https://mcp.corp.example/x", private_allowlist=listed)

        assert pinned.ips == ("10.9.9.9",)

    @pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254"])
    def test_a_listed_name_answering_loopback_or_metadata_is_refused(
        self, fake_dns: _Dns, address: str
    ) -> None:
        fake_dns({"wiki": [address]})
        listed = parse_private_allowlist(["wiki"])

        with pytest.raises(SSRFBlockedError):
            resolve_pinned_url("http://wiki/x", private_allowlist=listed)

    def test_validate_webhook_url_accepts_a_name_admitted_by_name_that_does_not_resolve_yet(
        self, fake_dns: _Dns
    ) -> None:
        asked = fake_dns({})
        listed = parse_private_allowlist(["wiki", ".corp.example"])

        assert validate_webhook_url("http://wiki/x", private_allowlist=listed) == "http://wiki/x"
        assert validate_webhook_url("http://a.corp.example/x", private_allowlist=listed)
        assert asked == ["wiki", "a.corp.example"]

    def test_validate_webhook_url_accepts_a_name_admitted_by_name_answering_a_private_address(
        self, fake_dns: _Dns
    ) -> None:
        fake_dns({"wiki": ["10.1.2.5"], "a.corp.example": ["fd12::5"]})
        listed = parse_private_allowlist(["wiki", ".corp.example"])

        assert validate_webhook_url("http://wiki/x", private_allowlist=listed)
        assert validate_webhook_url("http://a.corp.example/x", private_allowlist=listed)

    @pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "::1"])
    @pytest.mark.parametrize("entry", ["wiki", ".corp.example"])
    def test_validate_webhook_url_refuses_a_listed_name_answering_a_never_reachable_address(
        self, fake_dns: _Dns, entry: str, address: str
    ) -> None:
        """A suffix covers names a member can point anywhere, so listing a name
        never opens loopback or the metadata endpoint."""
        fake_dns({"wiki": [address], "a.corp.example": [address]})
        listed = parse_private_allowlist([entry])
        host = "wiki" if entry == "wiki" else "a.corp.example"

        with pytest.raises(SSRFBlockedError):
            validate_webhook_url(f"http://{host}/x", private_allowlist=listed)

    def test_a_name_not_listed_that_does_not_resolve_is_refused(self, fake_dns: _Dns) -> None:
        fake_dns({})
        listed = parse_private_allowlist(["wiki"])

        with pytest.raises(SSRFBlockedError):
            validate_webhook_url("http://other/x", private_allowlist=listed)

    def test_validate_webhook_url_resolves_a_host_admitted_only_by_a_network(
        self, fake_dns: _Dns
    ) -> None:
        asked = fake_dns({"wiki": ["10.1.2.5"], "other": ["10.1.3.5"]})
        listed = parse_private_allowlist(["10.1.2.0/24"])

        assert validate_webhook_url("http://wiki/x", private_allowlist=listed) == "http://wiki/x"
        with pytest.raises(SSRFBlockedError):
            validate_webhook_url("http://other/x", private_allowlist=listed)
        assert asked == ["wiki", "other"]

    def test_a_name_with_one_unlisted_ipv6_answer_is_refused_naming_that_address(
        self, fake_dns: _Dns
    ) -> None:
        fake_dns({"wiki": ["10.1.2.5", "fd12::5"]})
        listed = parse_private_allowlist(["10.1.2.0/24"])

        with pytest.raises(SSRFBlockedError) as raised:
            resolve_pinned_url("http://wiki/x", private_allowlist=listed)

        assert "fd12::5" in str(raised.value)
        assert "wiki" in str(raised.value)

    def test_a_refusal_never_quotes_the_url(
        self, caplog: pytest.LogCaptureFixture, fake_dns: _Dns
    ) -> None:
        fake_dns({"wiki": ["10.1.3.5"]})
        listed = parse_private_allowlist(["10.1.2.0/24"])

        with caplog.at_level(logging.DEBUG), pytest.raises(SSRFBlockedError) as raised:
            resolve_pinned_url("http://wiki/x?token=sh-secret", private_allowlist=listed)

        assert "sh-secret" not in str(raised.value)
        assert "token=" not in str(raised.value)
        assert all("sh-secret" not in record.getMessage() for record in caplog.records)
