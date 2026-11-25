"""Instance-local socket pinning for the locked botocore/urllib3 S3 transport.

Keep the SDK's endpoint, signer, pools and TLS names. Only the address passed
to a socket or a trusted deployment proxy changes. Proxy operators must honor
the numeric CONNECT/absolute-form target, as with the shared HTTP transport.
"""

import ipaddress
import socket
import sys
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from botocore.awsrequest import (
    AWSHTTPConnection,
    AWSHTTPConnectionPool,
    AWSHTTPSConnection,
    AWSHTTPSConnectionPool,
)
from botocore.client import BaseClient
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
from urllib3.util.timeout import _DEFAULT_TIMEOUT

from app.core.sanitize import deployment_allowlist, resolve_pinned_url


def _authority(host: str, port: int | None) -> str:
    host = f"[{host}]" if ":" in host else host
    return f"{host}:{port}" if port is not None else host


def _direct_socket(connection: HTTPConnection | HTTPSConnection) -> socket.socket:
    pinned = resolve_pinned_url(
        f"http://{_authority(connection._dns_host, connection.port)}",
        private_allowlist=deployment_allowlist(),
    )
    last_error: OSError | None = None
    for address in pinned.ips:
        family = socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        try:
            for option in connection.socket_options or ():
                sock.setsockopt(*option)
            if connection.timeout is not _DEFAULT_TIMEOUT:
                sock.settimeout(connection.timeout)
            if connection.source_address:
                sock.bind(connection.source_address)
            # No second getaddrinfo: both the family and destination are numeric.
            sock.connect((address, pinned.port))
            sys.audit("http.client.connect", connection, connection.host, connection.port)
        except OSError as exc:
            sock.close()
            last_error = exc
        except BaseException:
            sock.close()
            raise
        else:
            return sock
    if isinstance(last_error, TimeoutError):
        raise ConnectTimeoutError(connection, "S3 connection timed out") from last_error
    raise NewConnectionError(connection, "Could not connect to the S3 endpoint") from last_error


class _TunnelAddressFailed(OSError):
    def __init__(self, remaining: tuple[str, ...], cause: OSError) -> None:
        super().__init__("S3 proxy tunnel could not reach the vetted address")
        self.remaining = remaining
        self.cause = cause


def _tunnel(
    connection: AWSHTTPSConnection,
    original: Callable[[], None],
    candidates: tuple[str, ...] | None,
) -> None:
    host = connection._tunnel_host
    assert host is not None  # Called only for an SDK-configured CONNECT tunnel.
    try:
        pinned = resolve_pinned_url(
            f"https://{_authority(host, connection._tunnel_port)}",
            private_allowlist=deployment_allowlist(),
        )
        addresses = (
            pinned.ips if candidates is None else tuple(ip for ip in candidates if ip in pinned.ips)
        )
        if not addresses:
            # Refusal must close the already-open proxy socket.
            raise NewConnectionError(  # noqa: TRY301
                connection, "S3 endpoint addresses changed during proxy connection"
            )
        connection._tunnel_host = addresses[0]
        try:
            original()
        except OSError as exc:
            raise _TunnelAddressFailed(addresses[1:], exc) from exc
    except BaseException:
        connection.close()
        raise
    finally:
        # urllib3 uses this original name for origin SNI and certificate checks.
        connection._tunnel_host = host


def _forward_target(
    url: str, headers: Mapping[str, str | bytes]
) -> tuple[str, Mapping[str, str | bytes]]:
    parsed = urlsplit(url)
    if parsed.scheme != "http":
        return url, headers
    pinned = resolve_pinned_url(url, private_allowlist=deployment_allowlist())
    headers = dict(headers)
    if not any(key.lower() == "host" for key in headers):
        headers["Host"] = parsed.netloc
    return urlunsplit(parsed._replace(netloc=_authority(pinned.ips[0], parsed.port))), headers


def pin_s3_client(client: BaseClient) -> None:
    """Install pools owned by this client before its first provider operation.

    These are the private seams in botocore 1.44.3/urllib3 2.8.0. Retain the
    existing session so SDK CA, timeout, proxy and streaming configuration stay
    intact. Pool keys remain original origins, preventing cross-name TLS reuse.
    """

    class PinnedHTTPConnection(AWSHTTPConnection):
        def _new_conn(self) -> socket.socket:
            return super()._new_conn() if self.proxy else _direct_socket(self)

        def request(
            self,
            method: str,
            url: str,
            body: Any = None,
            headers: Mapping[str, str | bytes] | None = None,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            url, headers = _forward_target(url, headers or {})
            return super().request(method, url, body, headers, *args, **kwargs)

    class PinnedHTTPSConnection(AWSHTTPSConnection):
        _s3_tunnel_candidates: tuple[str, ...] | None = None
        _tunnel_headers: Mapping[str, str]

        def _new_conn(self) -> socket.socket:
            return super()._new_conn() if self.proxy else _direct_socket(self)

        def connect(self) -> None:
            host, port, scheme = self._tunnel_host, self._tunnel_port, self._tunnel_scheme
            if host is None:
                super().connect()
                return
            assert scheme is not None  # urllib3.set_tunnel assigns host and scheme together.
            headers = self._tunnel_headers
            self._s3_tunnel_candidates = None
            while True:
                try:
                    super().connect()
                except _TunnelAddressFailed as exc:
                    # Restart the SDK's whole connect sequence: its TLS code
                    # retains a local reference to the original proxy socket.
                    self.close()
                    if not exc.remaining:
                        raise exc.cause from exc
                    self.set_tunnel(host, port, headers=headers, scheme=scheme)
                    self._s3_tunnel_candidates = exc.remaining
                else:
                    return

        def _tunnel(self) -> None:
            # urllib3 inherits this private method from CPython; its runtime
            # implementation is inspected and exercised by real proxy tests.
            _tunnel(self, super()._tunnel, self._s3_tunnel_candidates)  # ty: ignore[missing-attribute]

        def request(
            self,
            method: str,
            url: str,
            body: Any = None,
            headers: Mapping[str, str | bytes] | None = None,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            # An HTTP origin may be forwarded over a TLS connection to its proxy.
            url, headers = _forward_target(url, headers or {})
            return super().request(method, url, body, headers, *args, **kwargs)

    class PinnedHTTPPool(AWSHTTPConnectionPool):
        # urllib3's protocol requires mutable default_socket_options but its
        # concrete connection declares that same inherited attribute Final.
        ConnectionCls = PinnedHTTPConnection  # ty: ignore[invalid-assignment]

    class PinnedHTTPSPool(AWSHTTPSConnectionPool):
        ConnectionCls = PinnedHTTPSConnection  # ty: ignore[invalid-assignment] -- same urllib3 Final mismatch

    session = client._endpoint.http_session
    session._pool_classes_by_scheme = {"http": PinnedHTTPPool, "https": PinnedHTTPSPool}
    session._manager.pool_classes_by_scheme = session._pool_classes_by_scheme
    for manager in session._proxy_managers.values():
        manager.pool_classes_by_scheme = session._pool_classes_by_scheme
