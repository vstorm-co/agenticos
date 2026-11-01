"""E2B cloud sandboxes on an organization's own account (#2305).

The workspace backend is the harness's `E2BSandboxBackend`; what this module adds
is the account. The harness reaches E2B with the SDK's default credential, the
process's `E2B_API_KEY`, which on a multi-tenant deployment would run every
organization's sandboxes on whichever account the operator happened to set -
the reason the Daytona connection passes its key explicitly too. The two calls
that reach E2B's control plane, create and attach, are made here with the
connection's key; every operation after them runs on the sandbox handle those
calls return, which carries the key with it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

import anyio
import e2b
from pydantic_ai.workspaces import WorkspaceRef, WorkspaceUnavailableError
from pydantic_ai_harness.e2b_sandbox import E2BSandboxBackend

PROVIDER = "e2b"

CREATE_SECONDS = 120.0
"""How long creating a sandbox may take before the run is told E2B did not answer."""

LIFETIME_SECONDS = 3600
"""A sandbox's lifetime per attach; E2B pauses it after, keeping its files."""


class OrgE2BBackend(E2BSandboxBackend):
    """The harness's E2B backend, on one organization's key."""

    def __init__(
        self,
        *,
        api_key: str,
        ref: WorkspaceRef | None = None,
        template: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(ref=ref, template=template, sandbox_timeout=LIFETIME_SECONDS, env=env)
        self._api_key = api_key
        self._org_template = template

    async def _create(self) -> e2b.AsyncSandbox:
        try:
            with anyio.fail_after(CREATE_SECONDS):
                return await e2b.AsyncSandbox.create(
                    template=self._org_template,
                    timeout=LIFETIME_SECONDS,
                    api_key=self._api_key,
                    # Paused rather than killed at the end of its lifetime, so the
                    # files a longer-scoped workspace keeps survive between runs.
                    lifecycle={"on_timeout": "pause"},
                )
        except e2b.AuthenticationException as exc:
            raise WorkspaceUnavailableError(
                "E2B refused this organization's key. Check the sandbox connection's key."
            ) from exc
        except e2b.ServiceBusyException as exc:
            raise WorkspaceUnavailableError(
                "E2B is busy; try creating the sandbox again later."
            ) from exc
        except e2b.SandboxException as exc:
            raise WorkspaceUnavailableError(f"E2B could not start a sandbox: {exc}") from exc
        except TimeoutError as exc:
            raise WorkspaceUnavailableError("E2B did not start a sandbox in time.") from exc

    async def _attach(self, sandbox_id: str) -> e2b.AsyncSandbox:
        try:
            with anyio.fail_after(CREATE_SECONDS):
                return await e2b.AsyncSandbox.connect(
                    sandbox_id, timeout=LIFETIME_SECONDS, api_key=self._api_key
                )
        except e2b.AuthenticationException as exc:
            raise WorkspaceUnavailableError(
                "E2B refused this organization's key. Check the sandbox connection's key."
            ) from exc
        except (e2b.SandboxException, e2b.ServiceBusyException) as exc:
            raise WorkspaceUnavailableError(
                "E2B could not reconnect to this sandbox; check its state and this connection. "
                "No replacement was created."
            ) from exc
        except TimeoutError as exc:
            raise WorkspaceUnavailableError(
                "E2B did not reconnect in time. No replacement was created."
            ) from exc


@dataclass(frozen=True)
class E2BWorkspace:
    """What supplies E2B sandboxes on one connection, as the Daytona capability does."""

    api_key: str = field(repr=False)
    template: str | None = None
    provider: str = PROVIDER

    def backend(self, ref: WorkspaceRef | None) -> OrgE2BBackend:
        """Attach to the sandbox `ref` names, or create one on first use."""
        return OrgE2BBackend(api_key=self.api_key, ref=ref, template=self.template)

    async def destroy(self, ref: WorkspaceRef) -> None:
        """Kill a sandbox, paused or running, without attaching to it - which would resume it."""
        await e2b.AsyncSandbox.kill(ref.id, api_key=self.api_key)
