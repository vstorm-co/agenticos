"""Permission introspection routes.

The frontend reads these to decide what to show. They are a convenience for the
UI and nothing more - the server re-checks every permission on the endpoint that
performs the action, so a client that ignores this API gains nothing.
"""

from typing import Any

from fastapi import APIRouter

from app.api.deps import Auth
from app.core.permissions import RESOURCE_PERMS, ROLE_PERMS, Perm
from app.schemas.permissions import (
    MyPermissions,
    PermissionEntry,
    RoleCatalog,
    RoleDefinition,
)

router = APIRouter()


@router.get("/me/permissions", response_model=MyPermissions)
async def get_my_permissions(ctx: Auth) -> Any:
    """Effective permissions for the caller in the active organization."""
    return MyPermissions(
        organization_id=str(ctx.organization_id),
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
