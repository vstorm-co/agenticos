"""One sharing API, generated per resource type.

Agents, collections and skills share the same sharing model - an owner, a
visibility, and a list of explicit grants - because the access rules underneath
them are deliberately resource-type agnostic. Writing the same four endpoints
three times would guarantee they drift: the fix applied to one, the field added
to another.

So the routes are built once and stamped out per type. What varies is only which
table a row is loaded from, which is the single argument this factory takes.

There *are* three routers, not one: `sharing.py` builds and names them, and each
is mounted under its own prefix with its own OpenAPI tags, so a client reading
the schema sees `/agents/{id}/sharing` and `/skills/{id}/sharing` as the
separate endpoints they are. What is shared is the definition, not the router.
Writing them out three times would buy nothing but three places to fix the next
bug in.

Nothing here builds a response body. Turning rows into `ResourceSharing` is
`ResourceSharing.of` - a route module that also owns serialization is how the
fourth resource type ends up with a subtly different payload.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Auth, DBSession, SharingSvc
from app.db.models.resource_grant import GrantLevel, Visibility
from app.schemas.resource_grant import (
    ResourceGrantRead,
    ResourceGrantUpsert,
    ResourceSharing,
    VisibilityUpdate,
)
from app.services.access import ResourceType
from app.services.sharing import SharingService

# Loads one row of this resource type inside an organization, or raises 404.
ResourceLoader = Callable[[AsyncSession, UUID, UUID], Awaitable[Any]]


def build_sharing_router(
    *,
    resource_type: ResourceType,
    load: ResourceLoader,
) -> APIRouter:
    """Four sharing endpoints for one resource type.

    The path parameter is `resource_id` for every type rather than `agent_id`,
    `kb_id` and so on: FastAPI binds path parameters by name, so per-type names
    would mean a separate handler per type - four near-identical functions for a
    cosmetic difference in the generated schema.

    Args:
        resource_type: Which permissions govern it, and the key stored on grants.
        load: How to fetch one row of it inside an organization.
    """
    router = APIRouter()

    async def _resolve(db: AsyncSession, resource_id: UUID, ctx: Any) -> Any:
        return await load(db, resource_id, ctx.organization_id)

    async def _sharing_of(service: SharingService, ctx: Any, resource: Any) -> ResourceSharing:
        grants, emails = await service.get_sharing(ctx, resource, resource_type=resource_type)
        return ResourceSharing.of(
            resource, resource_type=resource_type.key, grants=grants, emails=emails
        )

    @router.get("/{resource_id}/sharing", response_model=ResourceSharing)
    async def get_sharing(
        resource_id: UUID,
        db: DBSession,
        service: SharingSvc,
        ctx: Auth,
    ) -> Any:
        """Owner, visibility, and who this is shared with."""
        return await _sharing_of(service, ctx, await _resolve(db, resource_id, ctx))

    @router.put("/{resource_id}/sharing/grants", response_model=ResourceGrantRead)
    async def share(
        resource_id: UUID,
        data: ResourceGrantUpsert,
        db: DBSession,
        service: SharingSvc,
        ctx: Auth,
    ) -> Any:
        """Share with a member, or change the level they already have."""
        resource = await _resolve(db, resource_id, ctx)
        grant = await service.share(
            ctx,
            resource,
            resource_type=resource_type,
            subject_user_id=data.subject_user_id,
            level=GrantLevel(data.level),
        )
        return ResourceGrantRead(
            id=grant.id,
            subject_user_id=grant.subject_user_id,
            resource_type=grant.resource_type,
            resource_id=grant.resource_id,
            level=grant.level,
        )

    @router.delete(
        "/{resource_id}/sharing/grants/{subject_user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_model=None,
    )
    async def unshare(
        resource_id: UUID,
        subject_user_id: UUID,
        db: DBSession,
        service: SharingSvc,
        ctx: Auth,
    ) -> None:
        """Stop sharing with a member."""
        resource = await _resolve(db, resource_id, ctx)
        await service.revoke(
            ctx, resource, resource_type=resource_type, subject_user_id=subject_user_id
        )

    @router.patch("/{resource_id}/sharing/visibility", response_model=ResourceSharing)
    async def set_visibility(
        resource_id: UUID,
        data: VisibilityUpdate,
        db: DBSession,
        service: SharingSvc,
        ctx: Auth,
    ) -> Any:
        """Make it private, team-visible or org-visible."""
        resource = await _resolve(db, resource_id, ctx)
        await service.set_visibility(
            ctx, resource, resource_type=resource_type, visibility=Visibility(data.visibility)
        )
        return await _sharing_of(service, ctx, resource)

    return router
