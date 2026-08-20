# ruff: noqa: I001
"""Sync source service - org-scoped integration management."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.updates import writable
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.base import Base
from app.db.models.sync_source import SyncSource
from app.db.vector_tables import validate_collection_name
from app.services.access import SECRET, resolve_access
from app.services.rag.connectors import CONNECTOR_REGISTRY
from app.repositories import organization_secret_repo
from app.repositories import sync_log as sync_log_repo
from app.repositories import sync_source as sync_source_repo
from app.schemas.rag import RAGSyncLogItem, RAGSyncLogList
from app.schemas.sync_source import (
    ConnectorInfo,
    ConnectorList,
    SyncSourceClone,
    SyncSourceCreate,
    SyncSourceList,
    SyncSourceRead,
    SyncSourceUpdate,
)

# The credential field names the two shipped connectors used to hold in `config`.
# Kept as a list so a caller posting the old shape is told what to do instead of
# having the value silently dropped (#937).
_RETIRED_CREDENTIAL_FIELDS = frozenset(
    {"service_account_json", "access_key_id", "secret_access_key"}
)


async def _refuse_a_credential_in_the_config(config: dict, connector_type: str) -> None:
    """A config carrying something that looks like a credential is refused.

    The credential is a vault secret the source references by id, and `config`
    holds only what a connector needs to *find* the documents. A caller posting
    the old field names is a caller who has not been updated, and quietly
    dropping them would store a source that cannot authenticate and say nothing
    about why (#937).

    The names come from the connectors rather than a list here, so a connector
    added later inherits the refusal instead of having to remember it.
    """
    cls = CONNECTOR_REGISTRY.get(connector_type)
    if cls is None:
        return
    known = set(cls.CONFIG_SCHEMA)
    offending = sorted(name for name in _RETIRED_CREDENTIAL_FIELDS if name in config)
    unknown = sorted(name for name in offending if name not in known)
    if not unknown:
        return
    raise BadRequestError(
        message=(
            "A credential does not go in a source's configuration. Add it to the "
            "Vault and set `secret_id` instead."
        ),
        details={"connector_type": connector_type, "fields": unknown},
    )


async def _refuse_an_invalid_config(config: dict, connector_type: str) -> None:
    """Ask the connector whether it would accept this config, before it is stored.

    Every write path asks, so a value the connector refuses cannot be persisted
    by any of them. The alternative is a check that lives only on the sink -
    correct, but it answers in a background sync log rather than to the caller
    who sent the value, and only once somebody triggers a run.

    A field the connector named travels on as `details["fields"]`, rooted here
    because this is the layer that knows the shape of what was posted: the
    wizard sends its answers under `config`, so `folder_id` is `config.folder_id`
    to the form. Flattening it into the sentence is what left the wizard with
    four inputs and a line of prose saying one of them was wrong (#897).
    """
    connector_cls = CONNECTOR_REGISTRY.get(connector_type)
    if connector_cls is None:  # pragma: no cover - a stored row names a live connector
        return
    refusal = await connector_cls().validate_config(config)
    if refusal is None:
        return
    sentence = f"Invalid connector config: {refusal.message}"
    if refusal.field is None:
        raise BadRequestError(message=sentence, details={"connector_type": connector_type})
    raise refused_field(f"config.{refusal.field}", sentence, connector_type=connector_type)


def _raw_config(source: SyncSource) -> dict:
    c = source.config
    if isinstance(c, dict):
        return c
    if c:
        return json.loads(c)
    return {}


class SyncSourceService:
    """Service for managing sync source configurations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _to_read(self, s: SyncSource, *, secret_hint: str | None = None) -> SyncSourceRead:
        return SyncSourceRead(
            id=str(s.id),
            organization_id=str(s.organization_id),
            name=s.name,
            connector_type=s.connector_type,
            collection_name=s.collection_name,
            # Unmasked, because there is nothing here to mask: the credential is
            # `secret_id` and what it points at never leaves the vault (#937).
            config=_raw_config(s),
            secret_id=str(s.secret_id) if s.secret_id else None,
            secret_hint=secret_hint,
            sync_mode=s.sync_mode,
            schedule_minutes=s.schedule_minutes,
            is_active=s.is_active,
            last_sync_at=s.last_sync_at.isoformat() if s.last_sync_at else None,
            last_sync_status=s.last_sync_status,
            last_error=s.last_error,
            created_at=s.created_at.isoformat() if s.created_at else None,
        )

    async def list_sources(
        self,
        # Optional, and only for the operator CLI: `rag-sources` and
        # `rag-source-sync --all` are deployment-wide by design. Every HTTP
        # caller passes `ctx.organization_id`.
        organization_id: UUID | None = None,
        collection_name: str | None = None,
        is_active: bool | None = None,
    ) -> SyncSourceList:
        """List sync sources for an org, optionally filtered by KB collection."""
        sources = await sync_source_repo.get_all(
            self.db,
            organization_id=organization_id,
            collection_name=collection_name,
            is_active=is_active,
        )
        return SyncSourceList(items=[self._to_read(s) for s in sources], total=len(sources))

    async def get_source(self, source_id: str) -> SyncSource:
        """Get a sync source by ID.

        Raises:
            NotFoundError: If sync source does not exist.
        """
        source = await sync_source_repo.get_by_id(self.db, UUID(source_id))
        if not source:
            raise NotFoundError(
                message="Sync source not found",
                details={"source_id": source_id},
            )
        return source

    async def list_logs(self, source_id: UUID, *, limit: int = 20) -> RAGSyncLogList:
        """One source's run history, newest first.

        Both surfaces that show a source's history - a knowledge base's sync row
        and an org integration - read it here rather than each holding its own
        query and its own copy of this mapping. Whoever calls it has already
        decided the caller may see this source: an org integration resolves it
        through `CollectionAccessService`, and a KB route resolves it against the
        base in the path. Scope is not this method's to add, which is why it takes
        an id that has been through one of those.
        """
        logs = await sync_log_repo.get_all(self.db, sync_source_id=source_id, limit=limit)
        items = [
            RAGSyncLogItem(
                id=str(log.id),
                source=log.source,
                collection_name=log.collection_name,
                status=log.status,
                mode=log.mode,
                total_files=log.total_files,
                ingested=log.ingested,
                updated=log.updated,
                skipped=log.skipped,
                failed=log.failed,
                error_message=log.error_message,
                started_at=log.started_at,
                completed_at=log.completed_at,
            )
            for log in logs
        ]
        return RAGSyncLogList(items=items, total=len(items))

    async def create_source(self, data: SyncSourceCreate, *, ctx: AuthContext) -> SyncSourceRead:
        """Create a new sync source.

        Secret fields are Fernet-encrypted before persisting.
        `collection_name` is optional - omit to create an org-level integration
        not yet linked to a knowledge base.

        The name's *shape* is judged here rather than only at the routes,
        because a sync writes into whatever collection this row names and the
        store will interpolate it into DDL. A name no table can be called was
        accepted and then failed in a worker, attributed to the sync rather than
        to the configuration that caused it - which is the same class of failure
        #371 and #368 fixed on the route side, reaching the row through the CLI
        instead (#707).

        Whose collection it is remains the caller's question, because only the
        caller knows who is asking: the route resolves it with
        `CollectionAccessService.writable`, and `rag-source-add` resolves the
        organization it was given.

        Raises:
            BadRequestError: unknown connector, invalid config, or a collection
                name that cannot safely become an identifier.
        """
        if data.connector_type not in CONNECTOR_REGISTRY:
            raise BadRequestError(
                message=f"Unknown connector type: {data.connector_type}",
                details={"connector_type": data.connector_type},
            )

        if data.collection_name is not None:
            validate_collection_name(data.collection_name, metadata=Base.metadata)

        await _refuse_a_credential_in_the_config(data.config, data.connector_type)
        await _refuse_an_invalid_config(data.config, data.connector_type)
        hint = await self._checked_secret(data.secret_id, data.connector_type, ctx)

        source = await sync_source_repo.create(
            self.db,
            name=data.name,
            connector_type=data.connector_type,
            organization_id=ctx.organization_id,
            collection_name=data.collection_name,
            config=data.config,
            secret_id=data.secret_id,
            sync_mode=data.sync_mode,
            schedule_minutes=data.schedule_minutes,
        )
        return self._to_read(source, secret_hint=hint)

    async def _checked_secret(
        self, secret_id: UUID | None, connector_type: str, ctx: AuthContext
    ) -> str | None:
        """The credential's hint, having checked it is one this caller may bind.

        Three questions, and neither of the first two can be left to the foreign
        key. `organization_secrets.id` is unique across the deployment, so a
        caller who guesses one binds another organization's credential and the
        database is satisfied.

        **And the organization is not the whole of it.** A secret can be
        *private to a member*, and a sync runs for everyone who can reach the
        collection - so binding one is lending it, exactly as binding a
        capability's key is. A Builder holding `connections:manage` but only
        shared-secret visibility could otherwise post the id of another member's
        private credential and have the worker unseal it. That is #918 in this
        table, and `AgentRegistryService._binding_problems` is the shape of the
        answer: `resolve_access(..., Perm.SECRETS_VIEW, resource_type=SECRET)`,
        with the refusal phrased as a miss so it cannot enumerate the vault.

        The kind is asked because a connector cannot use the wrong one: an S3
        source given a service account fails at sync time, in a worker, with the
        reason in a log rather than on the form that chose it.

        **A context with no subject is checked for the tenant only**, because
        there is nobody to evaluate: `resolve_access` refuses a subjectless
        context outright, and the one caller that has none is `rag-source-add`,
        run by whoever has a shell on the deployment. The vault's visibility
        model is about members of an organization, not about the operator hosting
        it.

        Answers the vault's four-character hint so a reader can tell which
        credential a source uses without being shown it.
        """
        if secret_id is None:
            return None
        row = await organization_secret_repo.get(
            self.db, secret_id, organization_id=ctx.organization_id
        )
        # Refused as one the vault does not hold rather than as one belonging to
        # somebody else: the refusal must not confirm that an id exists.
        missing = refused_field("secret_id", "No such credential in this organization's vault")
        if row is None:
            raise missing
        if ctx.user_id is not None and not await resolve_access(
            self.db, ctx, row, Perm.SECRETS_VIEW, resource_type=SECRET
        ):
            raise missing
        required = CONNECTOR_REGISTRY[connector_type].SECRET_KIND
        if row.kind != required.value:
            raise refused_field(
                "secret_id",
                f"A {CONNECTOR_REGISTRY[connector_type].DISPLAY_NAME} source needs a "
                f"{required.value} credential, and that one is {row.kind}",
            )
        return row.hint

    async def clone_source(
        self, source_id: str, data: SyncSourceClone, *, organization_id: UUID
    ) -> SyncSourceRead:
        """Clone an existing integration into a different knowledge base.

        The clone *references the same vault secret* rather than copying a
        credential. That is the point of the id: one Drive credential feeding
        five collections is one secret, rotated once, and revoking it stops all
        five - where five encrypted copies had to be found first (#937).
        """
        existing = await self.get_source(source_id)
        raw = _raw_config(existing)
        # A clone copies a config somebody else's row already holds, and rows
        # predating this check exist. Judged again rather than trusted.
        await _refuse_an_invalid_config(raw, existing.connector_type)

        source = await sync_source_repo.create(
            self.db,
            name=data.name or f"{existing.name} (copy)",
            connector_type=existing.connector_type,
            organization_id=organization_id,
            collection_name=data.collection_name,
            config=raw,
            secret_id=existing.secret_id,
            sync_mode=existing.sync_mode,
            schedule_minutes=existing.schedule_minutes,
        )
        return self._to_read(source)

    async def update_source(
        self, source_id: str, data: SyncSourceUpdate, *, ctx: AuthContext
    ) -> SyncSourceRead:
        """Update an existing sync source.

        No `••••••` round-trip any more: the config holds no credential, so a
        patch has nothing to send back masked and nothing to skip on the way in
        (#937). Changing the credential means changing `secret_id`, which is
        checked the same way creation checks it.

        Raises:
            NotFoundError: If sync source does not exist.
            BadRequestError: The config carries a credential, the connector
                refuses it, or the credential named is not this organization's or
                not the kind the connector needs.
        """
        existing = await self.get_source(source_id)
        updates = writable(data, over=SyncSource)
        hint: str | None = None

        if "secret_id" in updates:
            hint = await self._checked_secret(updates["secret_id"], existing.connector_type, ctx)

        if "config" in updates and updates["config"] is not None:
            raw_existing = _raw_config(existing)
            merged: dict = {**raw_existing, **updates["config"]}
            await _refuse_a_credential_in_the_config(merged, existing.connector_type)
            # The merged config, not the patch: a caller sends one field and the
            # connector judges the whole thing it will actually run with. Asked
            # here as well as on create because `create_source` was the only
            # route that asked, so a value refused at creation could be reached
            # by patching it in afterwards - and the sink check inside the
            # connector then answered an hour later in a sync log rather than to
            # the caller who sent it.
            await _refuse_an_invalid_config(merged, existing.connector_type)
            updates["config"] = merged

        source = await sync_source_repo.update(self.db, UUID(source_id), **updates)
        if source is None:
            raise NotFoundError(message="Sync source not found", details={"source_id": source_id})
        return self._to_read(source, secret_hint=hint)

    async def delete_source(self, source_id: str) -> None:
        """Delete a sync source.

        Raises:
            NotFoundError: If sync source does not exist.
        """
        await self.get_source(source_id)
        await sync_source_repo.delete(self.db, UUID(source_id))

    async def trigger_sync(self, source_id: str) -> object:
        """Trigger a manual sync - persists a SyncLog and dispatches the task.

        Raises:
            NotFoundError: If sync source does not exist.
            BadRequestError: If source has no assigned collection.
        """

        source = await self.get_source(source_id)
        if not source.collection_name:
            raise BadRequestError(
                message="Cannot sync a source without an assigned knowledge base collection.",
                details={"source_id": source_id},
            )
        sync_log = await sync_log_repo.create(
            self.db,
            source=source.connector_type,
            collection_name=source.collection_name,
            mode=source.sync_mode,
            sync_source_id=source.id,
        )
        from app.core.background import spawn_after_commit
        from app.worker.tasks.rag_tasks import sync_single_source_flow

        # The flow reads this sync log by id on its own session, so it starts
        # after the commit rather than after this line (#417).
        spawn_after_commit(
            self.db,
            sync_single_source_flow(source_id, str(sync_log.id)),
            name=f"sync-source-{source_id}",
        )
        return sync_log

    async def update_after_sync(
        self,
        source_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """Update sync source status after a sync operation completes."""
        await sync_source_repo.update_sync_status(
            self.db,
            UUID(source_id),
            last_sync_at=datetime.now(UTC),
            last_sync_status=status,
            last_error=error,
        )

    @staticmethod
    def list_connectors() -> ConnectorList:
        """List available connector types, their config schemas and their credential.

        `secret_kind` is what the wizard needs to offer the organization's
        matching vault secrets and nothing else: a Drive source takes a service
        account, an S3 one an AWS key pair. It used to ask for the credential as
        a `secret: true` field in `config_schema`, which is the whole of what
        #937 removed.
        """
        return ConnectorList(
            items=[
                ConnectorInfo(
                    type=connector_cls.CONNECTOR_TYPE,
                    name=connector_cls.DISPLAY_NAME,
                    config_schema=dict(connector_cls.CONFIG_SCHEMA),
                    secret_kind=connector_cls.SECRET_KIND.value,
                    enabled=True,
                )
                for connector_cls in CONNECTOR_REGISTRY.values()
            ]
        )
