"""Context files - an organization's standing context, stored in the database.

A context file is a piece of standing knowledge written once and attached to
many agents: a glossary, a brand voice, an escalation matrix. This module owns
storage and access; turning context files into something a run reads - injected
into the instructions or exposed through a tool - is the context *capability*.
"""

from __future__ import annotations

import logging
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.context import ContextFile
from app.db.models.resource_grant import Visibility
from app.db.updates import writable
from app.repositories import context_repo, resource_grant_repo
from app.repositories.context import ContextSort
from app.schemas.context import (
    ContextFileList,
    ContextFileSummary,
    ContextFileUpdate,
    ContextModeLiteral,
)
from app.services.access import CONTEXT, resolve_access, visible_resource_ids

logger = logging.getLogger(__name__)


def _summary(file: ContextFile) -> ContextFileSummary:
    """A context file as the listing shows it - the body is a byte count only."""
    return ContextFileSummary(
        id=file.id,
        name=file.name,
        description=file.description,
        format=file.format,
        mode=cast(ContextModeLiteral, file.mode),
        enabled=file.enabled,
        size_bytes=len(file.content.encode("utf-8")),
    )


class ContextService:
    """Manage an organization's context files."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(
        self, ctx: AuthContext, context_id: UUID, *, perm: Perm = Perm.CONTEXT_VIEW
    ) -> ContextFile:
        file = await context_repo.get(self.db, context_id, organization_id=ctx.organization_id)
        if file is None:
            raise NotFoundError(
                message="Context file not found", details={"context_id": str(context_id)}
            )
        if not await resolve_access(self.db, ctx, file, perm, resource_type=CONTEXT):
            # 404, not 403: whether a private file exists is itself something the
            # caller may not learn.
            raise NotFoundError(
                message="Context file not found", details={"context_id": str(context_id)}
            )
        return file

    async def list_context(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        search: str | None = None,
        sort: ContextSort = "name",
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[ContextFile], int]:
        """A page of the context files this caller may see, and the total.

        Scoped like every shared resource: a role that reaches the whole
        organization lists everything, anyone else lists their own files, the
        org-visible ones and those explicitly shared with them - the same set
        :func:`resolve_access` admits one row at a time.
        """
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=CONTEXT, perm=Perm.CONTEXT_VIEW
        )
        grant_ids = [] if shared is None else shared
        if shared_with_me and shared is None:
            # A role that reaches everything never looks its grants up - but
            # "shared with me" is a question about grants and visibility, not
            # reach, so it has to ask even then.
            grant_ids = await resource_grant_repo.list_shared_ids(
                self.db,
                organization_id=ctx.organization_id,
                subject_user_id=ctx.subject_id,
                resource_type=CONTEXT.key,
            )
        return await context_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=grant_ids,
            shared_with_me=shared_with_me,
            search=search,
            sort=sort,
            skip=skip,
            limit=limit,
        )

    async def list_readable(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        search: str | None = None,
        sort: ContextSort = "name",
        skip: int = 0,
        limit: int = 50,
    ) -> ContextFileList:
        """The listing: a page of files and the unpaged total the pager needs."""
        items, total = await self.list_context(
            ctx,
            shared_with_me=shared_with_me,
            search=search,
            sort=sort,
            skip=skip,
            limit=limit,
        )
        return ContextFileList(items=[_summary(file) for file in items], total=total)

    async def resolve_for_agent(
        self, ctx: AuthContext, context_ids: list[UUID]
    ) -> list[ContextFile]:
        """The enabled context files an agent is bound to.

        Scoped to the run's organization and **not** to the runner's own access,
        the same rule skills, collections and delegates follow: the binding is
        checked once, against the publisher, when the agent is published, and the
        agent then reads it for everyone who may run it. See `_context_problems`
        in `app/services/agent_registry.py`.

        Re-checking here would break the surfaces this platform exists to serve -
        an API key, an embedded widget and a channel message all run without a
        subject, and `resolve_access` refuses every one of them - and would make
        an agent's instructions change with who asked. A file deleted or disabled
        after publish is skipped rather than failing the run: the agent is less
        capable, not broken. Order is preserved so injection order is the order
        the spec bound them in.
        """
        if not context_ids:
            return []
        found = await context_repo.get_many(
            self.db, context_ids, organization_id=ctx.organization_id
        )
        resolved = []
        for context_id in context_ids:
            file = found.get(context_id)
            if file is None or not file.enabled:
                logger.warning(
                    "Agent references context file %s which is disabled, deleted, or not org %s's",
                    context_id,
                    ctx.organization_id,
                )
                continue
            resolved.append(file)
        return resolved

    async def create(
        self,
        ctx: AuthContext,
        *,
        name: str,
        description: str | None,
        content: str,
        content_format: str = "md",
        mode: str = "inject",
        visibility: Visibility = Visibility.PRIVATE,
    ) -> ContextFile:
        """Create a context file.

        Raises:
            AlreadyExistsError: If the name is taken. The name is how the `link`
                tool and a person refer to a file, so two with one name is an
                ambiguity nothing can resolve.
        """
        if await context_repo.get_by_name(self.db, name, organization_id=ctx.organization_id):
            raise AlreadyExistsError(
                message=(
                    f"A context file named '{name}' already exists. Choose a different name, or "
                    "open the existing file and edit it, which reaches every agent bound to it."
                ),
                details={"name": name},
            )
        file = await context_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            owner_user_id=ctx.user_id,
            name=name,
            description=description,
            content=content,
            content_format=content_format,
            mode=mode,
            visibility=visibility.value,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="context.created",
            target_type="context",
            target_id=str(file.id),
            details={"name": name, "mode": mode},
        )
        return file

    async def update(
        self, ctx: AuthContext, context_id: UUID, data: ContextFileUpdate
    ) -> ContextFile:
        """Edit a context file. Every agent bound to it is current on the next run."""
        file = await self.get(ctx, context_id, perm=Perm.CONTEXT_EDIT)
        update_data = writable(data, over=ContextFile)
        updated = await context_repo.update(self.db, file=file, update_data=update_data)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="context.updated",
            target_type="context",
            target_id=str(file.id),
            # The submitted body is not echoed - an edit to a run's standing
            # context is worth attributing, the content of it is not audit data.
            details={"name": file.name, "fields": sorted(update_data)},
        )
        return updated

    async def delete(self, ctx: AuthContext, context_id: UUID) -> None:
        file = await self.get(ctx, context_id, perm=Perm.CONTEXT_EDIT)
        await resource_grant_repo.delete_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=CONTEXT.key,
            resource_id=file.id,
        )
        await context_repo.delete(self.db, file)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="context.deleted",
            target_type="context",
            target_id=str(context_id),
        )
