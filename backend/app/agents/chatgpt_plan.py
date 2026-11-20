"""The SDK's public Responses dialect with per-request grant revocation checks."""

from collections.abc import Awaitable, Callable

import httpx2
from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTCredentials, OpenAIChatGPTProvider

from app.services.chatgpt_plan import VaultChatGPTCredentials


class ChatGPTPlanProvider(OpenAIChatGPTProvider):
    def __init__(
        self, source: VaultChatGPTCredentials, *, http_client: httpx2.AsyncClient | None = None
    ) -> None:
        self._vault_source = source
        super().__init__(credential_source=source, http_client=http_client)

    async def _prepare_request_credentials(
        self,
    ) -> tuple[OpenAIChatGPTCredentials, Callable[[], Awaitable[OpenAIChatGPTCredentials]]]:
        # The SDK caches grants after the first load. This narrow lifecycle
        # override preserves its refresh owner while checking revocation on
        # every request, including its single 401 replay.
        await self._vault_source.assert_current()
        grant, replay = await super()._prepare_request_credentials()
        await self._vault_source.assert_current()

        async def authorized_replay() -> OpenAIChatGPTCredentials:
            await self._vault_source.assert_current()
            rotated = await replay()
            await self._vault_source.assert_current()
            return rotated

        return grant, authorized_replay
