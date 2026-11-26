"""The SDK receives a separate secret binding only on a host advertising its exact mount contract."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_ai_backends.workspaces import SandboxdWorkspace

from app.core.exceptions import ExternalServiceError
from app.db.models.sandbox_connection import SandboxConnection
from app.schemas.project_filesystem_authority import ProjectFilesystemCredential
from app.services import sandbox_workspace as workspace_module
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.sandbox_workspace import SandboxWorkspaceService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def resolved(kind: str = "docker") -> ResolvedConnection:
    return ResolvedConnection(
        row=SandboxConnection(
            id=uuid4(), kind=kind, base_url="https://sandbox.invalid", default_runtime="python"
        ),
        token="synthetic-service-token",
    )


async def test_workspace_uses_the_installed_sdk_secret_binding_without_leaking_it_in_repr() -> None:
    credential = ProjectFilesystemCredential(
        binding_id=uuid4(), token=SecretStr("synthetic-filesystem-token")
    )
    try:
        capability = SandboxWorkspaceService._service_capability(
            resolved(), "private-session", tenant="one-tenant", filesystem_binding=credential
        )
        assert isinstance(capability, SandboxdWorkspace)
        assert capability.filesystem_binding is not None
        assert capability.filesystem_binding.id == credential.binding_id
        assert (
            capability.filesystem_binding.token.get_secret_value()
            == credential.token.get_secret_value()
        )
        assert capability.filesystem_binding.token is credential.token
        assert "synthetic-filesystem-token" not in repr(capability)
        assert capability.session_name == "private-session" and capability.tenant == "one-tenant"
        legacy = SandboxWorkspaceService._service_capability(resolved(), "legacy-session")
        assert isinstance(legacy, SandboxdWorkspace) and legacy.filesystem_binding is None
    finally:
        await workspace_module.close_sandboxd_client()


@pytest.mark.parametrize("kind", ["daytona", "e2b", "opensandbox"])
async def test_non_docker_provider_does_not_claim_live_mount_support(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    service = SandboxConnectionService(AsyncMock())
    probe = AsyncMock()
    monkeypatch.setattr(service, "_read", probe)
    assert not await service.supports_project_filesystem(resolved(kind))
    probe.assert_not_awaited()


@pytest.mark.parametrize(
    ("payload", "supported"),
    [
        ({}, False),
        ({"filesystem_mounts": False, "filesystem_mount_path": "/project"}, False),
        ({"filesystem_mounts": True}, False),
        ({"filesystem_mounts": True, "filesystem_mount_path": "/other"}, False),
        ({"filesystem_mounts": True, "filesystem_mount_path": "/project"}, True),
    ],
)
async def test_legacy_or_wrong_path_policy_is_not_a_project_mount(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, object], supported: bool
) -> None:
    service = SandboxConnectionService(AsyncMock())
    probe = AsyncMock(return_value=payload)
    monkeypatch.setattr(service, "_read", probe)
    host = resolved()
    assert await service.supports_project_filesystem(host) is supported
    probe.assert_awaited_once_with(host, "/policy", host.row.id)


async def test_host_probe_failure_and_malformed_policy_are_not_silently_treated_as_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SandboxConnectionService(AsyncMock())
    probe = AsyncMock(side_effect=ExternalServiceError(message="Host unavailable"))
    monkeypatch.setattr(service, "_read", probe)
    with pytest.raises(ExternalServiceError):
        await service.supports_project_filesystem(resolved())
    probe.side_effect = None
    probe.return_value = {"filesystem_mounts": "invalid-boolean"}
    with pytest.raises(ValidationError):
        await service.supports_project_filesystem(resolved())
