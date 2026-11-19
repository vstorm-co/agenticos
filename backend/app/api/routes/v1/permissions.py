"""Permission introspection routes.

The frontend reads these to decide what to show. They are a convenience for the
UI and nothing more - the server re-checks every permission on the endpoint that
performs the action, so a client that ignores this API gains nothing.
"""

from typing import Any

from fastapi import APIRouter, Request

from app import __version__
from app.api.deps import Auth
from app.api.public_api import PUBLIC
from app.core.permissions import RESOURCE_PERMS, ROLE_PERMS, Perm
from app.schemas.permissions import (
    MyPermissions,
    PermissionEntry,
    PlatformContextRead,
    RoleCatalog,
    RoleDefinition,
)
from app.services.api_key import KeyCaller

router = APIRouter(dependencies=[PUBLIC])


@router.get("/me/platform-context", response_model=PlatformContextRead)
async def get_platform_context(request: Request, ctx: Auth) -> Any:
    """Versioned MCP feature discovery, distinct from effective authorization.

    Null scopes means a signed-in console session, not an unrestricted token.
    A token reports only its granted scopes; all routes still recheck access.
    """
    caller = getattr(request.state, "api_key_caller", None)
    return PlatformContextRead(
        server_version=__version__,
        mcp_contract_version=1,
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        authentication=caller.surface if isinstance(caller, KeyCaller) else "session",
        granted_scopes=(
            sorted(perm.value for perm in ctx.key_scopes) if ctx.key_scopes is not None else None
        ),
        features=["dependency_setup", "quality_lifecycle", "knowledge_sync", "solution_bundles"],
    )


@router.get("/me/permissions", response_model=MyPermissions)
async def get_my_permissions(ctx: Auth) -> Any:
    """Effective permissions for the caller in the active organization."""
    return MyPermissions(
        organization_id=str(ctx.organization_id),
        user_id=str(ctx.user_id),
        role=ctx.role,
        is_app_admin=ctx.is_app_admin,
        permissions=[
            PermissionEntry(permission=perm.value, scope=scope.value)
            for perm, scope in sorted(ctx.permissions.items(), key=lambda kv: kv[0].value)
        ],
    )


@router.get("/roles/catalog", response_model=RoleCatalog)
async def get_role_catalog(ctx: Auth) -> Any:
    """The full permission catalog and what each built-in role bundles.

    Readable by any member: it describes the platform's rules, not the
    organization's data, and the Users & Roles page needs it to render a matrix
    even for someone who cannot change roles.
    """
    return RoleCatalog(
        all_permissions=sorted(perm.value for perm in Perm),
        resource_permissions=sorted(perm.value for perm in RESOURCE_PERMS),
        roles=[
            RoleDefinition(
                name=role,
                permissions=[
                    PermissionEntry(permission=perm.value, scope=scope.value)
                    for perm, scope in sorted(perms.items(), key=lambda kv: kv[0].value)
                ],
            )
            for role, perms in ROLE_PERMS.items()
        ],
    )
