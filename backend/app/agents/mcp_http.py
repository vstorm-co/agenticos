"""Session-owned, DNS-pinned HTTP clients for remote MCP transports."""

from dataclasses import dataclass, field

import httpx2

from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import mcp_allowlist


@dataclass(frozen=True)
class McpHttpClientFactory:
    """Match both SDK factories; each session closes the client it creates."""

    url: str
    connect_timeout: float
    credential_origin: str | None = None
    default_timeout: httpx2.Timeout = field(
        default_factory=lambda: httpx2.Timeout(30.0, read=300.0)
    )

    def __call__(
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        follow_redirects: bool = False,
    ) -> PinnedAsyncClient:
        # MCP follows method-preserving, within-origin redirects itself. Turning
        # on HTTPX redirects would bypass that SDK policy before it sees them.
        del follow_redirects
        selected = timeout or self.default_timeout
        client = PinnedAsyncClient(
            timeout=httpx2.Timeout(
                connect=self.connect_timeout,
                read=selected.read,
                write=selected.write,
                pool=selected.pool,
            ),
            private_allowlist=mcp_allowlist(),
            allowlist_origin=self.url,
        )
        if headers is not None:
            client.headers.update(headers)
        if auth is not None:
            client.auth = auth
        if self.credential_origin is not None:
            expected = httpx2.URL(self.credential_origin)

            async def refuse_other_origin(request: httpx2.Request) -> None:
                actual = request.url
                if (actual.scheme, actual.host, actual.port) != (
                    expected.scheme,
                    expected.host,
                    expected.port,
                ):
                    raise httpx2.RequestError("Managed connection refused a cross-origin request.")

            client.event_hooks["request"].append(refuse_other_origin)
        return client
