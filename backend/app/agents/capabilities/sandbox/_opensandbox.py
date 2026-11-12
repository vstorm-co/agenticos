"""OpenSandbox workspaces on an organization's explicit server and vault key.

The pinned harness supplies file/command operations and reattaches by ref. This
adapter owns credentials and error disclosure; connection retries are disabled
because replaying sandbox creation or commands can repeat effects.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlsplit

import anyio
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.exceptions import SandboxException
from opensandbox.transport import RetryPolicy
from pydantic import SecretStr
from pydantic_ai.workspaces import (
    CommandResult,
    WorkspaceCommand,
    WorkspaceError,
    WorkspaceRef,
    WorkspaceUnavailableError,
)
from pydantic_ai_harness.opensandbox_sandbox import OpenSandbox, OpenSandboxBackend


class OrgOpenSandboxBackend(OpenSandboxBackend):
    """Keep server response bodies out of model-visible preparation failures."""

    async def _create(self) -> Sandbox:
        try:
            return await super()._create()
        except SandboxException, WorkspaceUnavailableError:
            raise WorkspaceUnavailableError(
                "OpenSandbox could not start a workspace. Check the connection's "
                "server, credential, image and available capacity."
            ) from None

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        try:
            return await super().run(command, shell=shell, env=env, timeout=timeout)
        except SandboxException:
            raise WorkspaceUnavailableError(
                "OpenSandbox could not complete this operation. Check the server and "
                "this connection. The existing workspace was not replaced."
            ) from None

    async def _attach(self, sandbox_id: str) -> Sandbox:
        try:
            return await super()._attach(sandbox_id)
        except SandboxException, WorkspaceUnavailableError:
            raise WorkspaceUnavailableError(
                "OpenSandbox could not reconnect to the existing workspace. Check its "
                "state and this connection. No replacement or empty workspace was created."
            ) from None


@dataclass(frozen=True)
class OpenSandboxWorkspace:
    server_url: str
    api_key: SecretStr = field(repr=False)
    image: str
    secure_access: bool = False

    def __post_init__(self) -> None:
        if not self.api_key.get_secret_value():
            # ConnectionConfig treats an empty key as permission to use the
            # process environment, which must never select a tenant's account.
            raise ValueError("An OpenSandbox connection needs its own API key")
        if urlsplit(self.server_url).scheme not in {"http", "https"}:
            raise ValueError("An OpenSandbox server address must use HTTP or HTTPS")
        if not self.image.strip():
            raise ValueError("An OpenSandbox connection needs a sandbox image")

    @property
    def provider(self) -> str:
        return "opensandbox"

    def connection(self) -> ConnectionConfig:
        """One SDK client configuration, with no deployment-wide credential fallback."""
        return ConnectionConfig(
            domain=self.server_url.rstrip("/"),
            protocol=urlsplit(self.server_url).scheme,
            api_key=self.api_key.get_secret_value(),
            request_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy.disabled(),
            use_server_proxy=True,
            disable_metrics=True,
        )

    def backend(self, ref: WorkspaceRef | None) -> OrgOpenSandboxBackend:
        """Attach when a ref exists; creation is reserved for a workspace's first use."""
        return OrgOpenSandboxBackend(
            image=self.image if ref is None else None,
            ref=ref,
            connection=self.connection(),
            sandbox_timeout=None,
            secure_access=self.secure_access,
        )

    async def destroy(self, ref: WorkspaceRef) -> None:
        """Delete only this recorded sandbox; the harness closes the manager transport."""
        try:
            await OpenSandbox[object](connection=self.connection()).destroy(ref)
        except SandboxException, WorkspaceUnavailableError:
            raise WorkspaceUnavailableError(
                "OpenSandbox could not remove the workspace. Check this connection; "
                "inspect the server for any sandbox still requiring cleanup."
            ) from None

    async def probe(self) -> None:
        """Check the server, key and image with one disposable sandbox, then remove it."""
        backend = self.backend(None)
        try:
            try:
                result = await backend.run(
                    ["sh", "-c", "printf agenticos-opensandbox-ok"], timeout=10
                )
                if result.exit_code != 0 or result.stdout != "agenticos-opensandbox-ok":
                    raise WorkspaceUnavailableError(
                        "The OpenSandbox image cannot run the workspace shell check"
                    )
            except SandboxException, WorkspaceError:
                raise WorkspaceUnavailableError(
                    "The OpenSandbox check failed. Verify the server address, vault key, "
                    "image, its POSIX shell tools and Secure Access deployment requirements."
                ) from None
        finally:
            with anyio.fail_after(30, shield=True):
                try:
                    ref = backend.ref
                    if ref is not None:
                        await self.destroy(ref)
                finally:
                    await backend.aclose()
