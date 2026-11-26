"""Keep the SDK's Copilot dialect without borrowing an editor's identity."""

from collections.abc import Awaitable, Callable, Mapping

import httpx
import httpx2
from openai import AsyncOpenAI
from pydantic_ai.providers.github_copilot import GitHubCopilotProvider

from app.clients.github_copilot import BASE_URL, HEADERS, bearer_token


class _CopilotClient(AsyncOpenAI):
    async def _prepare_request(self, request: httpx2.Request) -> None:
        await super()._prepare_request(request)
        # Request-level settings must not replace the account or application identity.
        request.headers.pop("editor-version", None)
        request.headers.pop("editor-plugin-version", None)
        request.headers.pop("x-api-key", None)
        request.headers.pop("api-key", None)
        request.headers.update(HEADERS)
        request.headers["Authorization"] = self.auth_headers["Authorization"]


class AgenticCopilotProvider(GitHubCopilotProvider):
    def __init__(
        self,
        token: str,
        *,
        http_client: httpx2.AsyncClient | None = None,
        token_source: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._token_source = token_source
        super().__init__(
            api_key=bearer_token(token),
            base_url=BASE_URL,
            integration_id="agenticos",
            http_client=http_client,
        )

    def _create_openai_client(
        self,
        *,
        base_url: str | None,
        api_key: str | Callable[[], Awaitable[str]] | None,
        http_client: httpx2.AsyncClient | httpx.AsyncClient | None,
        default_headers: Mapping[str, str] | None = None,
    ) -> AsyncOpenAI:
        # The SDK factory owns HTTP cleanup. Its default editor headers describe
        # VS Code; replacing them here preserves both lifecycle and our identity.
        client = self._get_http_client(http_client)
        if not isinstance(client, httpx2.AsyncClient):
            raise TypeError("Copilot requires an httpx2 client")
        key: str | Callable[[], Awaitable[str]] | None = api_key
        source = self._token_source
        if source is not None:

            async def load() -> str:
                return bearer_token(await source())

            key = load
        return _CopilotClient(
            base_url=BASE_URL, api_key=key, http_client=client, default_headers=HEADERS
        )
