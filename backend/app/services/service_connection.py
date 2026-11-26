"""Register, edit and look up service connections.

Who may do what follows who owns the row. An organization's rows are its
operators' - `connections:manage`, the permission the vault and the MCP
connections carry. The deployment's own rows (no organization) are the app
administrator's: every organization may *name* one, and an app-scoped collection
may name nothing else, but only the person running the deployment may say where
the deployment's Ollama or OCR server is.

What a row is for is checked when it is written, not when it is used. An
`embedding` connection names a provider from the embedding catalog that is reached
through a connection - `ollama`, whose catalog says which models it serves and at
what width, or `openai_compatible`, which serves any; an `ocr` one names the one
parser that sends pages out; a `document_parser` one names `docling`. Refused here, on the field, rather than discovered when
a collection's first document fails to index.

A connection may carry a key, and the rule is the one a collection's key follows:
only an organization's, from that organization's vault, that the caller may view,
and of the purpose the endpoint's API style takes. A deployment-owned row has no
vault, so it is keyless, and clearing a key from a keyed row is refused: the endpoint
would otherwise be called bare by every collection naming it.
"""

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.service_connection import ServiceConnection, ServiceConnectionKind
from app.db.updates import writable
from app.repositories import knowledge_base_repo, organization_secret_repo, service_connection_repo
from app.schemas.service_connection import (
    ServiceConnectionCreate,
    ServiceConnectionTest,
    ServiceConnectionTestResult,
    ServiceConnectionUpdate,
)
from app.services.access import SECRET, resolve_access
from app.services.embedding_probe_token import ProbeBinding, ProbePurpose, read_probe_token
from app.services.embedding_resolution import identify_connection, public_address
from app.services.rag import docling, embedding_providers
from app.services.rag.docling import DoclingTarget

logger = logging.getLogger(__name__)

OCR_PROVIDER = "liteparse"
"""The one parser that sends pages to an OCR server, and so the one `ocr` provider."""

DOCLING_PROVIDER = "docling"
"""The one provider a `document_parser` connection names."""

KEY_PURPOSES: dict[str, str] = {"openai_compatible": "openai_compatible", "docling": "docling"}
"""The vault purpose of the key a connection carries, by provider. A provider with no
entry takes no key."""

_PURPOSE_LABELS: dict[str, str] = {
    "openai_compatible": "an OpenAI-compatible endpoint",
    "docling": "a Docling Serve",
}


class ServiceConnectionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_visible(self, ctx: AuthContext) -> list[ServiceConnection]:
        """The organization's own services and the deployment's, in that order."""
        return await service_connection_repo.list_visible(
            self.db, organization_id=ctx.organization_id
        )

    async def get_visible(self, ctx: AuthContext, service_id: UUID) -> ServiceConnection:
        row = await service_connection_repo.get_visible(
            self.db, service_id, organization_id=ctx.organization_id
        )
        if row is None:
            raise NotFoundError(
                message="Service connection not found", details={"service_id": service_id}
            )
        return row

    async def create(self, ctx: AuthContext, data: ServiceConnectionCreate) -> ServiceConnection:
        """Register a service.

        Raises:
            AuthorizationError: If a deployment-wide row is asked for by somebody
                who is not the deployment's administrator.
            BadRequestError: If the provider does not fit the kind, or the key is
                not one this connection may carry - named on the field, because that
                is the control that was wrong.
            AlreadyExistsError: If the owner already has a row of that kind by
                that name.
        """
        owner = self._owner_for(ctx, deployment_wide=data.deployment_wide)
        _check_provider_fits(kind=data.kind, provider=data.provider)
        if data.secret_id is not None:
            await self._check_key(ctx, data.secret_id, owner=owner, provider=data.provider)
        await self._refuse_duplicate_name(owner, kind=data.kind, name=data.name)
        row = await service_connection_repo.create(
            self.db,
            organization_id=owner,
            kind=data.kind,
            provider=data.provider,
            name=data.name,
            base_url=data.base_url,
            created_by_user_id=ctx.subject_id,
            secret_id=data.secret_id,
            requires_key=data.secret_id is not None,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=owner,
            action="service_connection.created",
            target_type="service_connection",
            target_id=str(row.id),
            details={
                "name": row.name,
                "kind": row.kind,
                "provider": row.provider,
                "has_key": row.requires_key,
            },
        )
        return row

    async def update(
        self, ctx: AuthContext, service_id: UUID, data: ServiceConnectionUpdate
    ) -> ServiceConnection:
        """Edit a connection.

        Raises:
            BadRequestError: If the new key is not one this connection may carry,
                or the edit would clear the key of a keyed connection.
            AlreadyExistsError: If the new name is taken.
        """
        row = await self._editable(ctx, service_id)
        changes = writable(data, over=ServiceConnection, exclude={"probe_token", "unverified"})
        if "secret_id" in changes:
            new_key = changes["secret_id"]
            if new_key is None:
                if row.requires_key:
                    raise refused_field(
                        "secret_id",
                        "A keyed connection cannot be set back to no key: every collection "
                        "naming it would call the endpoint bare. Delete it and register "
                        "a keyless one instead.",
                    )
                del changes["secret_id"]
            elif new_key == row.secret_id:
                del changes["secret_id"]
            else:
                await self._check_key(
                    ctx, new_key, owner=row.organization_id, provider=row.provider
                )
        if (
            row.secret_id is not None
            and row.organization_id is not None
            and "secret_id" not in changes
            and changes.get("base_url", row.base_url) != row.base_url
        ):
            # The retained key would be sent to the new host: lending it, as
            # choosing it is, takes the right to view it.
            await self._viewable_key(ctx, row.secret_id, owner=row.organization_id)
        if "name" in changes and changes["name"] != row.name:
            await self._refuse_duplicate_name(
                row.organization_id, kind=row.kind, name=changes["name"]
            )
        if not changes:
            return row
        fields = sorted(changes)
        previous = _address_and_key(row.base_url, row.secret_id)
        new_base_url = changes.get("base_url", row.base_url)
        new_secret_id = changes.get("secret_id", row.secret_id)
        moves = row.kind == ServiceConnectionKind.EMBEDDING.value and (
            new_base_url != row.base_url or new_secret_id != row.secret_id
        )
        affected = await knowledge_base_repo.list_by_endpoint(self.db, row.id) if moves else []
        if moves and not data.unverified:
            await self._require_tested(
                ctx,
                row,
                token=data.probe_token,
                base_url=new_base_url,
                secret_id=new_secret_id,
                keyed=row.requires_key or "secret_id" in changes,
                affected=affected,
            )
        if "secret_id" in changes:
            changes["requires_key"] = True
        updated = await service_connection_repo.update(self.db, row=row, update_data=changes)
        details: dict[str, object]
        if moves and data.unverified:
            action = "service_connection.updated_unverified"
            details = {
                "previous": previous,
                "new": _address_and_key(new_base_url, new_secret_id),
                "knowledge_bases": [str(kb.id) for kb in affected],
                "fields": fields,
            }
        else:
            action = "service_connection.updated"
            details = {"fields": fields}
            if moves:
                details["verified"] = True
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=row.organization_id,
            action=action,
            target_type="service_connection",
            target_id=str(service_id),
            details=details,
        )
        return updated

    async def _viewable_key(
        self, ctx: AuthContext, secret_id: UUID, *, owner: UUID
    ) -> OrganizationSecret:
        """The vault row, if the caller may view it; otherwise "not in the vault".

        A missing row and one out of reach answer alike, so a refusal cannot
        enumerate another member's private secrets.
        """
        row = await organization_secret_repo.get(self.db, secret_id, organization_id=owner)
        if row is None or not await resolve_access(
            self.db, ctx, row, Perm.SECRETS_VIEW, resource_type=SECRET
        ):
            raise BadRequestError(
                message="That key is not in this organization's vault",
                details={"secret_id": str(secret_id)},
            )
        return row

    async def _require_tested(
        self,
        ctx: AuthContext,
        row: ServiceConnection,
        *,
        token: str | None,
        base_url: str,
        secret_id: UUID | None,
        keyed: bool,
        affected: Sequence[KnowledgeBase],
    ) -> None:
        """Refuse a move of an embedding connection that no passing test vouches for.

        The proof is bound to the address, the key (by id and by its current
        value's generation) and every knowledge base using the connection right now,
        so one attached since the test, or a key rotated since, voids it.

        Raises:
            BadRequestError: On `probe_token`.
        """
        claims = read_probe_token(token, ctx=ctx, purpose=ProbePurpose.CONNECTION_CHANGE)
        identity = await identify_connection(
            self.db,
            row,
            provider=row.provider,
            base_url=base_url,
            secret_id=secret_id,
            requires_key=keyed,
        )
        claims.require_match(
            ProbeBinding.of(
                ProbePurpose.CONNECTION_CHANGE,
                identity,
                model=None,
                dim=None,
                knowledge_bases=affected,
            )
        )

    async def _check_key(
        self, ctx: AuthContext, secret_id: UUID, *, owner: UUID | None, provider: str
    ) -> None:
        """Refuse a key this connection may not carry.

        The sibling of `KnowledgeBaseService._check_embedding_secret`, gate for gate.
        Binding a key is lending it: every collection naming the connection sends it
        to the endpoint. So the caller has to be able to reach the key themselves -
        the picker only offers what they can see, but the API takes an id and an id
        is guessable. A key they cannot view is phrased as one the vault does not
        hold, so a refusal cannot enumerate another member's private secrets.

        Raises:
            BadRequestError: On `secret_id`, for a deployment-owned connection, an
                API style that takes no key, a key outside the caller's reach, or a
                key of another purpose.
        """
        if owner is None:
            raise refused_field(
                "secret_id",
                "A deployment-wide connection cannot carry a key: the vault belongs to an "
                "organization. Register the connection inside an organization to give it one.",
            )
        purpose = KEY_PURPOSES.get(provider)
        if purpose is None:
            raise refused_field("secret_id", f"A {provider} connection takes no key.")
        row = await self._viewable_key(ctx, secret_id, owner=owner)
        if row.purpose != purpose:
            raise refused_field(
                "secret_id",
                f"That key is for {row.purpose}, and a {provider} connection sends its key to "
                f"{_PURPOSE_LABELS[provider]}. Create a key with the {purpose} purpose.",
                purpose=row.purpose,
            )

    async def test(
        self, ctx: AuthContext, data: ServiceConnectionTest
    ) -> ServiceConnectionTestResult:
        """Ask a Docling Serve whether it is one and accepts the key, storing nothing.

        The key is named by id: a vault key of the organization the caller may view, or
        the one a connection of theirs already holds. A stored key sent to an address
        other than the stored one is being lent to that host, so choosing it takes the
        right to view it, as it does on an edit.

        Raises:
            BadRequestError: On `kind` or `provider` when this is not a Docling
                connection, on `service_id` for a row that is not one, and on `secret_id`
                for a key the caller may not use.
            AuthorizationError: If `service_id` is a deployment-wide row and the caller
                is not the deployment's administrator.
        """
        if data.kind != ServiceConnectionKind.DOCUMENT_PARSER.value:
            raise refused_field("kind", "Only a document parser connection can be tested here.")
        if data.provider != DOCLING_PROVIDER:
            raise refused_field(
                "provider",
                f"A document parser is reached by {DOCLING_PROVIDER}, its only provider.",
            )
        base_url = data.base_url.rstrip("/")
        api_key: str | None = None
        if data.secret_id is not None:
            owner = ctx.organization_id
            await self._check_key(ctx, data.secret_id, owner=owner, provider=data.provider)
            api_key = await self._unseal_key(ctx, data.secret_id, owner=owner)
        elif data.service_id is not None:
            row = await self._editable(ctx, data.service_id)
            if (
                row.kind != ServiceConnectionKind.DOCUMENT_PARSER.value
                or row.provider != DOCLING_PROVIDER
            ):
                raise refused_field("service_id", "That connection is not a Docling Serve.")
            if row.secret_id is not None and row.organization_id is not None:
                if base_url != row.base_url.rstrip("/"):
                    await self._viewable_key(ctx, row.secret_id, owner=row.organization_id)
                api_key = await self._unseal_key(
                    ctx, row.secret_id, owner=row.organization_id, field="service_id"
                )
        result = await docling.probe(
            DoclingTarget(connection_id=data.service_id, base_url=base_url, api_key=api_key)
        )
        return ServiceConnectionTestResult(outcome=result.outcome, version=result.version)

    async def _unseal_key(
        self, ctx: AuthContext, secret_id: UUID, *, owner: UUID | None, field: str = "secret_id"
    ) -> str:
        """The value of an API key in an organization's vault, for one outbound call.

        Raises:
            BadRequestError: If the key is gone, cannot be unsealed or is not an API key.
                What went wrong inside the vault goes to the log, not the message.
        """
        assert owner is not None  # `_check_key` refuses a deployment-owned row first
        row = await organization_secret_repo.get(self.db, secret_id, organization_id=owner)
        if row is None:
            raise refused_field(field, "That key is not in this organization's vault.")
        try:
            secret = unseal_secret(
                row.sealed_secret,
                kind=SecretKind(row.kind),
                scope=VaultScope.organization(owner),
                key_version=row.key_version,
            )
        except Exception as exc:
            logger.warning("docling_test_key_unusable", extra={"error_type": type(exc).__name__})
            raise refused_field(
                field, "That key could not be unsealed. Store it again, or choose another."
            ) from exc
        if not isinstance(secret, ApiKeySecret):
            raise refused_field(field, "That vault entry does not hold an API key.")
        return secret.api_key.get_secret_value()

    async def delete(self, ctx: AuthContext, service_id: UUID) -> None:
        """Remove a service.

        A collection naming it keeps its row: `knowledge_bases.embedding_endpoint_id`
        is `SET NULL` on delete, and the resolver then says the service is gone,
        which is the truth and a state somebody can fix.
        """
        row = await self._editable(ctx, service_id)
        await service_connection_repo.delete(self.db, row=row)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=row.organization_id,
            action="service_connection.deleted",
            target_type="service_connection",
            target_id=str(service_id),
            details={"name": row.name, "kind": row.kind},
        )

    async def _editable(self, ctx: AuthContext, service_id: UUID) -> ServiceConnection:
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
        existing = await service_connection_repo.get_by_name(
            self.db, organization_id=owner, kind=kind, name=name
        )
        if existing is not None:
            raise AlreadyExistsError(
                message="A service of that kind by that name already exists",
                details={"name": name, "kind": kind},
            )


def _address_and_key(base_url: str, secret_id: UUID | None) -> dict[str, str | None]:
    """A connection's address and key as an audit entry keeps them: no query, no value."""
    return {
        "base_url": public_address(base_url),
        "secret_id": None if secret_id is None else str(secret_id),
    }


def _check_provider_fits(*, kind: str, provider: str) -> None:
    if kind == ServiceConnectionKind.EMBEDDING.value:
        entry = embedding_providers.get(provider)
        if entry is None or not entry.via_connection:
            reached = ", ".join(
                e.provider for e in embedding_providers.providers() if e.via_connection
            )
            raise refused_field(
                "provider",
                f"An embedding connection is a provider from the catalog that is reached through "
                f"one; choose one of: {reached}. A vendor with its own address is chosen on "
                "the collection, with the key that pays.",
            )
    elif kind == ServiceConnectionKind.OCR.value:
        if provider != OCR_PROVIDER:
            raise refused_field(
                "provider",
                f"An OCR server is reached by {OCR_PROVIDER}; that is the only provider.",
            )
    elif provider != DOCLING_PROVIDER:
        raise refused_field(
            "provider",
            f"A document parser is reached by {DOCLING_PROVIDER}; that is the only provider.",
        )
