"""The actual direct and CONNECT paths keep the checked IP and TLS hostname."""

import asyncio
import socket
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from httpcore2._backends.auto import AutoBackend
from httpcore2._backends.base import AsyncNetworkStream

from app.agents.mcp_http import McpHttpClientFactory

pytestmark = [pytest.mark.anyio, pytest.mark.security]
PUBLIC = "93.184.216.34"
HOST = "mcp.example.test"


@pytest.fixture
def certificate(tmp_path: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "fixture.crt", tmp_path / "fixture.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@asynccontextmanager
async def _https_server(
    certificate: tuple[Path, Path], names: list[str | None], requests: list[bytes]
) -> AsyncIterator[int]:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(*certificate)

    def server_name(_socket: ssl.SSLSocket, name: str | None, _context: ssl.SSLContext) -> None:
        names.append(name)

    context.set_servername_callback(server_name)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            requests.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=context)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()


@asynccontextmanager
async def _connect_proxy(target_port: int, connects: list[bytes]) -> AsyncIterator[int]:
    handlers: set[asyncio.Task[None]] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        current = asyncio.current_task()
        assert current is not None
        handlers.add(current)
        upstream: asyncio.StreamWriter | None = None
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            connects.append(request)
            assert (
                request.split(b"\r\n", 1)[0] == f"CONNECT {PUBLIC}:{target_port} HTTP/1.1".encode()
            )
            incoming, upstream = await asyncio.open_connection("127.0.0.1", target_port)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def copy(source: asyncio.StreamReader, dest: asyncio.StreamWriter) -> None:
                try:
                    while chunk := await source.read(65536):
                        dest.write(chunk)
                        await dest.drain()
                finally:
                    dest.close()

            async with asyncio.TaskGroup() as group:
                group.create_task(copy(reader, upstream))
                group.create_task(copy(incoming, writer))
        finally:
            writer.close()
            if upstream is not None:
                upstream.close()
            handlers.remove(current)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()
        if handlers:
            await asyncio.wait_for(asyncio.gather(*handlers), 3)


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("wrong_name", [False, True])
async def test_the_numeric_dial_and_connect_tunnel_preserve_real_tls_verification(
    certificate: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, proxied: bool, wrong_name: bool
) -> None:
    names: list[str | None] = []
    requests: list[bytes] = []
    connects: list[bytes] = []
    lookups: list[str] = []
    dials: list[str] = []
    hostname = "wrong.example.test" if wrong_name else HOST
    context = ssl.create_default_context(cafile=str(certificate[0]))
    real_transport = httpx2.AsyncHTTPTransport
    real_resolve = socket.getaddrinfo
    real_connect = AutoBackend.connect_tcp

    def transport(*args: object, **kwargs: object) -> httpx2.AsyncHTTPTransport:
        kwargs["verify"] = context
        return real_transport(*args, **kwargs)

    def resolve(host: str, port: int, *args: object, **kwargs: object) -> list[tuple[object, ...]]:
        if host == hostname:
            lookups.append(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC, port))]
        assert host == "127.0.0.1"
        return real_resolve(host, port, *args, **kwargs)

    async def connect(
        self: AutoBackend, host: str, port: int, **kwargs: object
    ) -> AsyncNetworkStream:
        dials.append(host)
        assert host == ("127.0.0.1" if proxied else PUBLIC)
        return await real_connect(self, "127.0.0.1", port, **kwargs)

    for variable in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        monkeypatch.delenv(variable, raising=False)
    async with (
        _https_server(certificate, names, requests) as port,
        _connect_proxy(port, connects) as proxy_port,
    ):
        if proxied:
            monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy_port}")
        monkeypatch.setattr("httpx2._client.AsyncHTTPTransport", transport)
        monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", resolve)
        monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
        url = f"https://{hostname}:{port}/mcp"
        client = McpHttpClientFactory(url, 2)()
        async with client:
            if wrong_name:
                with pytest.raises(httpx2.ConnectError, match="certificate verify failed"):
                    await client.get(url)
            else:
                assert (await client.get(url)).text == "ok"
        assert client.is_closed

    assert lookups == [hostname]
    assert names and set(names) == {hostname}
    assert dials
    assert bool(connects) == proxied
    if wrong_name:
        assert requests == []
    else:
        assert len(requests) == 1
        assert f"Host: {hostname}:{port}\r\n".encode() in requests[0]
