"""Folders of apps, skills, context files and knowledge bases (#2124).

A folder is a tree node with an audience. The access rules stay in
`resolve_access`; this service keeps the two invariants that let them:

- a resource filed in a folder carries the folder's `visibility`, written when
  it is filed and again whenever the folder's audience changes;
- a subfolder's audience is inside its parent's - never a wider visibility,
  and only subjects the parent names - checked when it is created, moved or
  re-audienced, and restored in every descendant when a parent narrows.

The folder's grants reach what it holds through `resource_grant_repo`, so a
member outside a folder's audience cannot list, read or bind what is in it -
through the console, the API or MCP alike - unless it was shared with them
directly.
"""

from typing import NamedTuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.folder import Folder
from app.db.models.resource_grant import ResourceGrant, Visibility
from app.repositories import folder_repo, resource_grant_repo
from app.repositories.folder import FolderScope
from app.schemas.folder import FolderCreate, FolderUpdate
from app.schemas.resource_grant import AudienceChoice
from app.services.access import (
    FOLDER_TYPES,
    FOLDERED,
    Filed,
    OwnedResource,
    accessible_ids,
    resolve_access,
)
from app.services.sharing import SharingService

# How wide each visibility reaches, for "never wider than the parent".
_WIDTH = {Visibility.PRIVATE.value: 0, Visibility.TEAM.value: 1, Visibility.ORG.value: 2}


class Subject(NamedTuple):
    """A person or a group a folder's audience names."""

    user_id: UUID | None
    group_id: UUID | None


class FolderView(NamedTuple):
    """A folder with what its reader is shown beside it."""

    folder: Folder
    group_ids: list[UUID]
    user_ids: list[UUID]
    item_count: int
    can_edit: bool


def _subjects(grants: list[ResourceGrant]) -> set[Subject]:
    return {Subject(grant.subject_user_id, grant.subject_group_id) for grant in grants}


class FolderService:
    """Folders of one organization, under the permissions of the kind they hold."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.sharing = SharingService(db)

    async def _grants(self, ctx: AuthContext, folder: Folder) -> list[ResourceGrant]:
        return await resource_grant_repo.list_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type="folder",
            resource_id=folder.id,
        )

    async def _view(self, ctx: AuthContext, folder: Folder, counts: dict[UUID, int]) -> FolderView:
        grants = await self._grants(ctx, folder)
        return FolderView(
            folder=folder,
            group_ids=[g.subject_group_id for g in grants if g.subject_group_id is not None],
            user_ids=[g.subject_user_id for g in grants if g.subject_user_id is not None],
            item_count=counts.get(folder.id, 0),
            can_edit=await resolve_access(
                self.db,
                ctx,
                folder,
                FOLDER_TYPES[folder.kind].edit,
                resource_type=FOLDER_TYPES[folder.kind],
            ),
        )

    async def list(self, ctx: AuthContext, *, kind: str) -> list[FolderView]:
        """The folders of one kind its reader can see - owner, audience or a grant."""
        folders = await folder_repo.list_for_kind(
            self.db, organization_id=ctx.organization_id, kind=kind
        )
        visible = await accessible_ids(
            self.db, ctx, folders, FOLDER_TYPES[kind].view, resource_type=FOLDER_TYPES[kind]
        )
        counts = await folder_repo.counts(self.db, organization_id=ctx.organization_id, kind=kind)
        return [await self._view(ctx, folder, counts) for folder in folders if folder.id in visible]

    async def get(self, ctx: AuthContext, *, kind: str, folder_id: UUID) -> Folder:
        """A folder of this kind the caller can see, or a 404 - never a 403 that confirms it."""
        folder = await folder_repo.get(
            self.db, organization_id=ctx.organization_id, folder_id=folder_id
        )
        if (
            folder is None
            or folder.kind != kind
            or not await resolve_access(
                self.db, ctx, folder, FOLDER_TYPES[kind].view, resource_type=FOLDER_TYPES[kind]
            )
        ):
            raise NotFoundError(message="Folder not found", details={"folder_id": folder_id})
        return folder

    async def scope(self, ctx: AuthContext, *, kind: str, folder: str | None) -> FolderScope | None:
        """What a listing's `folder` parameter asks for: `top`, one folder, or every folder."""
        if folder is None:
            return None
        folders = await folder_repo.list_for_kind(
            self.db, organization_id=ctx.organization_id, kind=kind
        )
        visible = frozenset(
            await accessible_ids(
                self.db, ctx, folders, FOLDER_TYPES[kind].view, resource_type=FOLDER_TYPES[kind]
            )
        )
        if folder == "top":
            return FolderScope(folder_id=None, visible=visible)
        try:
            folder_id = UUID(folder)
        except ValueError:
            raise refused_field("folder", "Name a folder by its id, or `top`.") from None
        if folder_id not in visible:
            raise NotFoundError(message="Folder not found", details={"folder_id": folder_id})
        return FolderScope(folder_id=folder_id, visible=visible)

    async def view(self, ctx: AuthContext, folder: Folder) -> FolderView:
        counts = await folder_repo.counts(
            self.db, organization_id=ctx.organization_id, kind=folder.kind
        )
        return await self._view(ctx, folder, counts)

    async def _require_edit(self, ctx: AuthContext, folder: Folder) -> None:
        if not await resolve_access(
            self.db,
            ctx,
            folder,
            FOLDER_TYPES[folder.kind].edit,
            resource_type=FOLDER_TYPES[folder.kind],
        ):
            raise AuthorizationError(
                message="You cannot change this folder", details={"folder_id": folder.id}
            )

    async def _check_inside(
        self, ctx: AuthContext, parent: Folder | None, audience: AudienceChoice
    ) -> None:
        """Refuse an audience wider than the parent's - a subfolder only narrows."""
        if parent is None or parent.visibility == Visibility.ORG.value:
            return
        if _WIDTH[audience.visibility.value] > _WIDTH[parent.visibility]:
            raise refused_field(
                "visibility", f"A folder inside {parent.name} cannot reach more than it does."
            )
        allowed = _subjects(await self._grants(ctx, parent))
        asked = {Subject(None, group) for group in audience.group_ids} | {
            Subject(user, None) for user in audience.user_ids if user != ctx.user_id
        }
        if not asked <= allowed:
            raise refused_field(
                "group_ids", f"Choose only the groups and people {parent.name} is shared with."
            )

    async def create(self, ctx: AuthContext, *, kind: str, data: FolderCreate) -> Folder:
        parent = (
            None
            if data.parent_id is None
            else await self.get(ctx, kind=kind, folder_id=data.parent_id)
        )
        await self._check_inside(ctx, parent, data)
        folder = await folder_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            kind=kind,
            parent_id=parent.id if parent else None,
            name=data.name,
            owner_user_id=ctx.user_id,
            visibility=data.visibility.value,
        )
        await self.sharing.restrict_to(
            ctx,
            folder,
            resource_type=FOLDER_TYPES[kind],
            group_ids=data.group_ids,
            user_ids=data.user_ids,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="folder.created",
            target_type="folder",
            target_id=str(folder.id),
            details={
                "kind": kind,
                "parent_id": str(folder.parent_id) if folder.parent_id else None,
            },
        )
        return folder

    async def _is_inside(self, ctx: AuthContext, candidate: Folder, ancestor: Folder) -> bool:
        """Whether `candidate` is `ancestor` or somewhere beneath it."""
        current: Folder | None = candidate
        while current is not None:
            if current.id == ancestor.id:
                return True
            current = (
                None
                if current.parent_id is None
                else await folder_repo.get(
                    self.db, organization_id=ctx.organization_id, folder_id=current.parent_id
                )
            )
        return False

    async def update(self, ctx: AuthContext, folder: Folder, data: FolderUpdate) -> Folder:
        await self._require_edit(ctx, folder)
        changes: dict[str, object] = {}
        if data.name is not None:
            changes["name"] = data.name
        parent: Folder | None = None
        moving = data.to_top or data.parent_id is not None
        if data.parent_id is not None and not data.to_top:
            parent = await self.get(ctx, kind=folder.kind, folder_id=data.parent_id)
            if await self._is_inside(ctx, parent, folder):
                raise refused_field("parent_id", "A folder cannot go inside itself.")
        if moving:
            changes["parent_id"] = parent.id if parent else None
        folder = await folder_repo.update_folder(self.db, folder=folder, update_data=changes)
        if moving and parent is not None:
            # Moved under a narrower parent: it, and everything beneath it, fits
            # inside the new parent's audience from here on.
            await self._narrow_to(ctx, folder, parent)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="folder.updated",
            target_type="folder",
            target_id=str(folder.id),
            details={"fields": sorted(changes)},
        )
        return folder

    async def set_audience(
        self, ctx: AuthContext, folder: Folder, audience: AudienceChoice
    ) -> Folder:
        """Replace who a folder reaches, and carry it to everything inside."""
        await self._require_edit(ctx, folder)
        parent = (
            None
            if folder.parent_id is None
            else await folder_repo.get(
                self.db, organization_id=ctx.organization_id, folder_id=folder.parent_id
            )
        )
        await self._check_inside(ctx, parent, audience)
        wanted = {Subject(None, group) for group in audience.group_ids} | {
            Subject(user, None) for user in audience.user_ids if user != ctx.user_id
        }
        await self._replace_grants(ctx, folder, wanted)
        folder = await folder_repo.update_folder(
            self.db, folder=folder, update_data={"visibility": audience.visibility.value}
        )
        await self._carry_down(ctx, folder)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="folder.audience_changed",
            target_type="folder",
            target_id=str(folder.id),
            details={
                "visibility": audience.visibility.value,
                "groups": len(audience.group_ids),
                "people": len(audience.user_ids),
            },
        )
        return folder

    async def _replace_grants(self, ctx: AuthContext, folder: Folder, wanted: set[Subject]) -> None:
        have = _subjects(await self._grants(ctx, folder))
        resource_type = FOLDER_TYPES[folder.kind]
        dropped = have - wanted
        for group_id in [s.group_id for s in dropped if s.group_id is not None]:
            await self.sharing.revoke_group(
                ctx, folder, resource_type=resource_type, group_id=group_id
            )
        for user_id in [s.user_id for s in dropped if s.user_id is not None]:
            await self.sharing.revoke(
                ctx, folder, resource_type=resource_type, subject_user_id=user_id
            )
        added = wanted - have
        await self.sharing.restrict_to(
            ctx,
            folder,
            resource_type=resource_type,
            group_ids=[s.group_id for s in added if s.group_id is not None],
            user_ids=[s.user_id for s in added if s.user_id is not None],
        )

    async def _narrow_to(self, ctx: AuthContext, folder: Folder, parent: Folder) -> None:
        """Fit a folder's audience inside its parent's, then its contents and children."""
        if parent.visibility != Visibility.ORG.value:
            if _WIDTH[folder.visibility] > _WIDTH[parent.visibility]:
                folder = await folder_repo.update_folder(
                    self.db, folder=folder, update_data={"visibility": parent.visibility}
                )
            allowed = _subjects(await self._grants(ctx, parent))
            await self._replace_grants(
                ctx, folder, _subjects(await self._grants(ctx, folder)) & allowed
            )
        await self._carry_down(ctx, folder)

    async def _carry_down(self, ctx: AuthContext, folder: Folder) -> None:
        """Write a folder's visibility onto what it holds, and narrow its subfolders."""
        await folder_repo.sync_contents_visibility(
            self.db,
            organization_id=ctx.organization_id,
            kind=folder.kind,
            folder_id=folder.id,
            visibility=folder.visibility,
        )
        for child in await folder_repo.children(
            self.db, organization_id=ctx.organization_id, folder_id=folder.id
        ):
            await self._narrow_to(ctx, child, folder)

    async def delete(self, ctx: AuthContext, folder: Folder, *, move_to: UUID | None) -> None:
        """Delete a folder, refiling what it holds - into `move_to`, or the top level."""
        await self._require_edit(ctx, folder)
        target = (
            None if move_to is None else await self.get(ctx, kind=folder.kind, folder_id=move_to)
        )
        if target is not None and await self._is_inside(ctx, target, folder):
            raise refused_field("move_to", "Move its contents somewhere outside it.")
        await folder_repo.move_contents(
            self.db,
            organization_id=ctx.organization_id,
            kind=folder.kind,
            from_folder_id=folder.id,
            to_folder_id=target.id if target else None,
        )
        if target is not None:
            await self._carry_down(ctx, target)
        await resource_grant_repo.delete_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type="folder",
            resource_id=folder.id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="folder.deleted",
            target_type="folder",
            target_id=str(folder.id),
            details={"moved_to": str(target.id) if target else None},
        )
        await folder_repo.delete(self.db, folder=folder)

    async def file(
        self, ctx: AuthContext, *, kind: str, resource: OwnedResource, folder_id: UUID | None
    ) -> None:
        """File a resource in a folder, or take it out to the top level.

        The resource is the caller's to change, and the folder one they can see.
        Filed, it carries the folder's visibility; taken out, it keeps what it
        had, so a move to the top level never widens who reaches it.
        """
        resource_type = FOLDERED[kind]
        if not isinstance(resource, Filed):
            raise BadRequestError(message="This resource cannot be filed", details={"kind": kind})
        if not await resolve_access(
            self.db, ctx, resource, resource_type.edit, resource_type=resource_type
        ):
            raise AuthorizationError(
                message="You cannot move this", details={"resource_id": resource.id}
            )
        folder = None if folder_id is None else await self.get(ctx, kind=kind, folder_id=folder_id)
        resource.folder_id = folder.id if folder else None
        if folder is not None:
            resource.visibility = folder.visibility
        self.db.add(resource)
        await self.db.flush()
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="resource.filed",
            target_type=resource_type.key,
            target_id=str(resource.id),
            details={"folder_id": str(folder.id) if folder else None},
        )
