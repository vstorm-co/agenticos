"""`doctor`'s line for `OUTBOUND_PRIVATE_ALLOWLIST`.

A listed network is reachable by every member of every organization, so the
line has to say when one is wide and when one covers the stores this deployment
runs on. DNS is stubbed: nothing here touches the network.
"""

import socket
from collections.abc import Callable

import pytest

from app.commands import doctor
from app.commands.doctor import _private_network
from app.core.config import settings

pytestmark = pytest.mark.anyio


def _answering(addresses: dict[str, str]) -> Callable[..., list[tuple[object, ...]]]:
    def getaddrinfo(
        host: str, port: object, *args: object, **kwargs: object
    ) -> list[tuple[object, ...]]:
        if host not in addresses:
            raise socket.gaierror(socket.EAI_NONAME, "unknown")
        family = socket.AF_INET6 if ":" in addresses[host] else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (addresses[host], 0))]

    return getaddrinfo


@pytest.fixture(autouse=True)
def _stores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "POSTGRES_HOST", "db.internal.example")
    monkeypatch.setattr(settings, "REDIS_HOST", "cache.internal.example")
    monkeypatch.setattr(
        doctor.socket,
        "getaddrinfo",
        _answering({"db.internal.example": "172.20.0.2", "cache.internal.example": "172.20.0.3"}),
    )


def _listed(monkeypatch: pytest.MonkeyPatch, *entries: str) -> None:
    monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", list(entries))


def _mcp_listed(monkeypatch: pytest.MonkeyPatch, *entries: str) -> None:
    monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", list(entries))


async def test_an_empty_list_is_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    _listed(monkeypatch)

    status, detail = await _private_network()

    assert status == "unconfigured"
    assert "OUTBOUND_PRIVATE_ALLOWLIST" in detail


async def test_entries_are_listed_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _listed(monkeypatch, "wiki", ".corp.example", "10.1.2.0/24")

    status, detail = await _private_network()

    assert status == "healthy"
    assert "wiki, .corp.example, 10.1.2.0/24" in detail


@pytest.mark.parametrize("entry", ["10.0.0.0/15", "10.0.0.0/8", "fd00::/47", "fd00::/32"])
async def test_a_range_wider_than_a_slash_16_is_a_warning(
    monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    _listed(monkeypatch, "wiki", entry)

    status, detail = await _private_network()

    assert status == "not_checked"
    assert entry in detail


@pytest.mark.parametrize("entry", ["10.0.0.0/16", "10.0.0.5", "fd00::/48", "fd00::1"])
async def test_a_range_at_the_limit_is_not_a_warning(
    monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    _listed(monkeypatch, entry)

    status, _ = await _private_network()

    assert status == "healthy"


@pytest.mark.parametrize(
    ("host", "name", "address"),
    [
        ("POSTGRES_HOST", "db.internal.example", "10.1.2.3"),
        ("REDIS_HOST", "cache.internal.example", "10.1.2.3"),
        ("POSTGRES_HOST", "db.internal.example", "fd00:1::5"),
    ],
)
async def test_a_range_covering_a_store_address_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch, host: str, name: str, address: str
) -> None:
    monkeypatch.setattr(doctor.socket, "getaddrinfo", _answering({name: address}))
    _listed(monkeypatch, "fd00:1::/64" if ":" in address else "10.1.0.0/16")

    status, detail = await _private_network()

    assert status == "unhealthy"
    assert host in detail


async def test_a_wide_range_covering_a_store_is_unhealthy_not_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        doctor.socket, "getaddrinfo", _answering({"db.internal.example": "10.1.2.3"})
    )
    _listed(monkeypatch, "10.0.0.0/8")

    status, _ = await _private_network()

    assert status == "unhealthy"


async def test_an_unresolvable_store_host_is_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.socket, "getaddrinfo", _answering({}))
    _listed(monkeypatch, "10.1.0.0/16")

    status, _ = await _private_network()

    assert status == "healthy"


async def test_a_store_host_that_cannot_be_encoded_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refusing(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        raise UnicodeError("label too long")

    monkeypatch.setattr(doctor.socket, "getaddrinfo", refusing)
    _listed(monkeypatch, "10.1.0.0/16")

    status, _ = await _private_network()

    assert status == "healthy"


async def test_the_mcp_list_alone_is_reported_with_its_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _listed(monkeypatch)
    _mcp_listed(monkeypatch, "postgres-mcp")

    status, detail = await _private_network()

    assert status == "healthy"
    assert detail == "MCP_ALLOWED_HOSTS admits postgres-mcp"


async def test_both_lists_are_named_when_both_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _listed(monkeypatch, "wiki")
    _mcp_listed(monkeypatch, "postgres-mcp")

    _, detail = await _private_network()

    assert detail == "OUTBOUND_PRIVATE_ALLOWLIST admits wiki; MCP_ALLOWED_HOSTS admits postgres-mcp"


async def test_an_empty_list_names_both_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    _listed(monkeypatch)
    _mcp_listed(monkeypatch)

    status, detail = await _private_network()

    assert status == "unconfigured"
    assert "OUTBOUND_PRIVATE_ALLOWLIST and MCP_ALLOWED_HOSTS are empty" in detail


async def test_an_mcp_range_covering_a_store_address_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _listed(monkeypatch)
    _mcp_listed(monkeypatch, "172.20.0.0/24")

    status, detail = await _private_network()

    assert status == "unhealthy"
    assert "MCP_ALLOWED_HOSTS admits 172.20.0.0/24" in detail
    assert "OUTBOUND_PRIVATE_ALLOWLIST" not in detail
    assert "POSTGRES_HOST" in detail


async def test_a_wide_mcp_range_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _listed(monkeypatch)
    _mcp_listed(monkeypatch, "10.0.0.0/8")

    status, detail = await _private_network()

    assert status == "not_checked"
    assert "10.0.0.0/8" in detail
