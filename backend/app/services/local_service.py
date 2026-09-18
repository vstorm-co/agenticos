"""Register, edit and look up the services on the deployment's own network.

Who may do what follows who owns the row. An organization's rows are its
operators' - `connections:manage`, the permission the vault and the MCP
connections carry. The deployment's own rows (no organization) are the app
administrator's: every organization may *name* one, and an app-scoped collection
may name nothing else, but only the person running the deployment may say where
the deployment's Ollama or OCR server is.

What a row is for is checked when it is written, not when it is used. An
`embedding` service names a keyless provider from the embedding catalog, because
the catalog is what says which models the service serves and at what width; an
`ocr` service names the one parser that sends pages out. Refused here, on the
field, rather than discovered when a collection's first document fails to index.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.local_service import LocalService, LocalServiceKind
from app.db.updates import writable
from app.repositories import local_service_repo
from app.schemas.local_service import LocalServiceCreate, LocalServiceUpdate
from app.services.rag import embedding_providers

OCR_PROVIDER = "liteparse"
"""The one parser that sends pages to an OCR server, and so the one `ocr` provider."""


class LocalServiceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_visible(self, ctx: AuthContext) -> list[LocalService]:
        """The organization's own services and the deployment's, in that order."""
        return await local_service_repo.list_visible(self.db, organization_id=ctx.organization_id)

    async def get_visible(self, ctx: AuthContext, service_id: UUID) -> LocalService:
        row = await local_service_repo.get_visible(
            self.db, service_id, organization_id=ctx.organization_id
        )
        if row is None:
            raise NotFoundError(
                message="Local service not found", details={"service_id": service_id}
            )
        return row

    async def create(self, ctx: AuthContext, data: LocalServiceCreate) -> LocalService:
        """Register a service.

        Raises:
            AuthorizationError: If a deployment-wide row is asked for by somebody
                who is not the deployment's administrator.
            BadRequestError: If the provider does not fit the kind - named on the
                field, because that is the select that was wrong.
            AlreadyExistsError: If the owner already has a row of that kind by
                that name.
        """
        owner = self._owner_for(ctx, deployment_wide=data.deployment_wide)
        _check_provider_fits(kind=data.kind, provider=data.provider)
        await self._refuse_duplicate_name(owner, kind=data.kind, name=data.name)
        row = await local_service_repo.create(
            self.db,
            organization_id=owner,
            kind=data.kind,
            provider=data.provider,
            name=data.name,
            base_url=data.base_url,
            created_by_user_id=ctx.subject_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=owner,
            action="local_service.created",
            target_type="local_service",
            target_id=str(row.id),
            details={"name": row.name, "kind": row.kind, "provider": row.provider},
        )
        return row

    async def update(
        self, ctx: AuthContext, service_id: UUID, data: LocalServiceUpdate
    ) -> LocalService:
        row = await self._editable(ctx, service_id)
        changes = writable(data, over=LocalService)
        if "name" in changes and changes["name"] != row.name:
            await self._refuse_duplicate_name(
                row.organization_id, kind=row.kind, name=changes["name"]
            )
        return await local_service_repo.update(self.db, row=row, update_data=changes)

    async def delete(self, ctx: AuthContext, service_id: UUID) -> None:
        """Remove a service.

        A collection naming it keeps its row: `knowledge_bases.embedding_endpoint_id`
        is `SET NULL` on delete, and the resolver then says the service is gone,
        which is the truth and a state somebody can fix.
        """
        row = await self._editable(ctx, service_id)
        await local_service_repo.delete(self.db, row=row)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=row.organization_id,
            action="local_service.deleted",
            target_type="local_service",
            target_id=str(service_id),
            details={"name": row.name, "kind": row.kind},
        )

    async def _editable(self, ctx: AuthContext, service_id: UUID) -> LocalService:
        """A row this caller may change: the organization's own, or the
        deployment's for its administrator. A visible row is not an editable one."""
        row = await self.get_visible(ctx, service_id)
        if row.organization_id is None and not ctx.is_app_admin:
            raise AuthorizationError(
                message="Only the deployment's administrator can change a deployment-wide service",
                details={"service_id": service_id},
            )
        return row

    @staticmethod
    def _owner_for(ctx: AuthContext, *, deployment_wide: bool) -> UUID | None:
        if not deployment_wide:
            return ctx.organization_id
        if not ctx.is_app_admin:
            raise AuthorizationError(
                message="Only the deployment's administrator can register a deployment-wide service"
            )
        return None

    async def _refuse_duplicate_name(self, owner: UUID | None, *, kind: str, name: str) -> None:
        existing = await local_service_repo.get_by_name(
            self.db, organization_id=owner, kind=kind, name=name
        )
        if existing is not None:
            raise AlreadyExistsError(
                message="A service of that kind by that name already exists",
                details={"name": name, "kind": kind},
            )


def _check_provider_fits(*, kind: str, provider: str) -> None:
    if kind == LocalServiceKind.EMBEDDING.value:
        entry = embedding_providers.get(provider)
        if entry is None or not entry.keyless:
            keyless = ", ".join(e.provider for e in embedding_providers.providers() if e.keyless)
            raise refused_field(
                "provider",
                f"An embedding service is a keyless provider from the catalog; choose one of: "
                f"{keyless}. A vendor that takes a key is chosen on the collection, with the "
                "key that pays.",
            )
    elif provider != OCR_PROVIDER:
        raise refused_field(
            "provider", f"An OCR server is reached by {OCR_PROVIDER}; that is the only provider."
        )
