"""OpenSandbox selection, validation and explicit organization probe credentials."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from pydantic_ai.workspaces import WorkspaceUnavailableError

from app.agents.capabilities.sandbox._opensandbox import OpenSandboxWorkspace
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.sandbox_connection import SandboxConnection
from app.schemas.sandbox_connection import SandboxProbeRequest
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.sandbox_workspace import SandboxWorkspaceService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("secure", [False, True])
def test_the_selected_connection_owns_its_image_and_secure_access(secure: bool) -> None:
    row = SandboxConnection(
        id=uuid4(),
        kind="opensandbox",
        base_url="https://sandbox.example",
        default_runtime="python:3.12-slim",
        secure_access=secure,
    )
    resolved = ResolvedConnection(row=row, token="org-key")
    workspace = SandboxWorkspaceService._service_capability(resolved, "scope")
    assert isinstance(workspace, OpenSandboxWorkspace)
    assert workspace.image == row.default_runtime
    assert workspace.secure_access is secure
    assert workspace.api_key == SecretStr("org-key")
    overridden = SandboxWorkspaceService._service_capability(
        resolved, "scope", runtime="alpine:3.22"
    )
    assert isinstance(overridden, OpenSandboxWorkspace)
    assert overridden.image == "alpine:3.22"


@pytest.mark.parametrize("image", [None, "", "  ", "python :3.12", "https://registry/image"])
def test_an_image_that_cannot_start_is_refused_before_the_first_run(image: str | None) -> None:
    with pytest.raises(BadRequestError, match="container image reference"):
        SandboxConnectionService._check_shape(
            kind="opensandbox", base_url="https://sandbox.example", default_runtime=image
        )


@pytest.mark.parametrize("kind", ["docker", "e2b", "daytona"])
def test_secure_access_cannot_be_saved_on_an_unrelated_provider(kind: str) -> None:
    with pytest.raises(BadRequestError, match="Secure Access"):
        SandboxConnectionService._check_shape(
            kind=kind,
            base_url="https://sandbox.example",
            default_runtime="python",
            secure_access=True,
        )


@pytest.mark.security
async def test_an_opensandbox_probe_never_borrows_the_deployment_docker_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "deployment-key")
    service = SandboxConnectionService(MagicMock())
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    with pytest.raises(BadRequestError, match="Pick the key"):
        await service._probe_token(
            ctx,
            SandboxProbeRequest(
                kind="opensandbox",
                base_url="http://sandboxd:8080",
                default_runtime="python:3.12-slim",
            ),
        )


@pytest.mark.parametrize("secure", [False, True])
async def test_the_manual_probe_checks_the_selected_image_and_mode(
    monkeypatch, secure: bool
) -> None:
    service = SandboxConnectionService(MagicMock())
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    monkeypatch.setattr(service, "_probe_token", AsyncMock(return_value="organization-key"))
    seen: list[OpenSandboxWorkspace] = []

    async def check(workspace: OpenSandboxWorkspace) -> None:
        seen.append(workspace)

    monkeypatch.setattr(OpenSandboxWorkspace, "probe", check)
    data = SandboxProbeRequest(
        kind="opensandbox",
        base_url="https://sandbox.example",
        default_runtime="python:3.12-slim",
        secure_access=secure,
    )
    policy = await service.probe_policy(ctx, data)
    assert len(seen) == 1
    assert seen[0].secure_access is secure
    assert seen[0].image == data.default_runtime
    assert seen[0].api_key == SecretStr("organization-key")
    assert policy.kind == "opensandbox" and policy.default_runtime == data.default_runtime
    monkeypatch.setattr(
        OpenSandboxWorkspace,
        "probe",
        AsyncMock(side_effect=WorkspaceUnavailableError("Check the server and image")),
    )
    with pytest.raises(BadRequestError, match="Check the server and image"):
        await service.probe_policy(ctx, data)


def test_long_images_are_supported_without_expanding_other_providers_runtime_names() -> None:
    image = "registry.example/" + "a" * 180 + ":latest"
    SandboxConnectionService._check_shape(
        kind="opensandbox", base_url="https://sandbox.example", default_runtime=image
    )
    with pytest.raises(BadRequestError, match="64 characters"):
        SandboxConnectionService._check_shape(kind="e2b", base_url=None, default_runtime=image)


@pytest.mark.parametrize("missing", ["address", "image"])
def test_an_incomplete_stored_connection_is_an_actionable_failure(missing: str) -> None:
    row = SandboxConnection(
        id=uuid4(),
        kind="opensandbox",
        base_url=None if missing == "address" else "https://sandbox.example",
        default_runtime=None if missing == "image" else "python:3.12-slim",
        secure_access=False,
    )
    with pytest.raises(BadRequestError, match="server address and sandbox image"):
        SandboxWorkspaceService._service_capability(
            ResolvedConnection(row=row, token="org-key"), "scope"
        )
