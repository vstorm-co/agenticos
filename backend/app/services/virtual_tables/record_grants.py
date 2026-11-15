"""Manage explicit record grants separately from record data writes."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from app.core.audit import record_audit
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import GrantLevel
from app.db.models.virtual_table import VirtualTableRecord
from app.repositories import group_repo, member_repo, resource_grant_repo, virtual_table_repo
from app.repositories import task as task_repo
from app.schemas.table_record_access import RecordAccessRead, RecordGrantRead, RecordGrantUpdate
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.row_policy import may_view_row, parse_policy

RECORD_RESOURCE = "table_record"


class RecordAccessOperations(Operations):
    """Row sharing requires table administration; a row Write grant is insufficient."""

    async def _access_record(
        self, ctx: AuthContext, table_id: UUID, record_id: UUID, *, lock: bool = False
    ) -> VirtualTableRecord:
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, share=lock)
        self._ensure_live(table)
        parse_policy(table.row_policy)
        if await task_repo.for_table(self.db, table.id, ctx.organization_id) is not None:
            raise BadRequestError(
                message="Managed task boards use their board access rules",
                details={"table_id": table.id},
            )
        record = await virtual_table_repo.get_record(
            self.db,
            record_id,
            table_id=table.id,
            organization_id=ctx.organization_id,
            for_update=lock,
        )
        if record is None or not await may_view_row(
            self.db, ctx, table, await self._columns(table), record.values, record_id=record_id
        ):
            raise NotFoundError(message="Record not found", details={"record_id": record_id})
        return record

    async def get_record_access(
        self, ctx: AuthContext, table_id: UUID, record_id: UUID
    ) -> RecordAccessRead:
        """List the row's grants for an administrator who can read the row."""
        await self._access_record(ctx, table_id, record_id)
        return await self._access_read(ctx, table_id, record_id)

    async def _access_read(
        self, ctx: AuthContext, table_id: UUID, record_id: UUID
    ) -> RecordAccessRead:
        grants = await resource_grant_repo.list_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=RECORD_RESOURCE,
            resource_id=record_id,
        )
        emails = await member_repo.get_emails_for_users(
            self.db,
            organization_id=ctx.organization_id,
            user_ids=[grant.subject_user_id for grant in grants if grant.subject_user_id],
        )
        names = await group_repo.get_names(
            self.db,
            organization_id=ctx.organization_id,
            group_ids=[grant.subject_group_id for grant in grants if grant.subject_group_id],
        )
        return RecordAccessRead(
            table_id=table_id,
            record_id=record_id,
            grants=[
                RecordGrantRead(
                    id=grant.id,
                    subject_user_id=grant.subject_user_id,
                    subject_email=emails.get(grant.subject_user_id)
                    if grant.subject_user_id
                    else None,
                    subject_group_id=grant.subject_group_id,
                    subject_group_name=names.get(grant.subject_group_id)
                    if grant.subject_group_id
                    else None,
                    level="write" if grant.level == GrantLevel.EDIT.value else "read",
                    expires_at=grant.expires_at,
                )
                for grant in grants
                if grant.level in (GrantLevel.READ.value, GrantLevel.EDIT.value)
            ],
        )

    async def set_record_grant(
        self, ctx: AuthContext, table_id: UUID, record_id: UUID, data: RecordGrantUpdate
    ) -> RecordAccessRead:
        """Grant Read or Write inside this table; do not change table access or row values."""
        await self._access_record(ctx, table_id, record_id, lock=True)
        expires_at = data.expires_at
        if data.subject_group_id is not None and expires_at is None:
            expires_at = datetime.now(UTC) + timedelta(days=90)
        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise BadRequestError(message="Choose an expiry in the future", details={})
        level = GrantLevel.EDIT if data.level == "write" else GrantLevel.READ
        if data.subject_user_id is not None:
            membership = await member_repo.get(
                self.db, organization_id=ctx.organization_id, user_id=data.subject_user_id
            )
            if membership is None:
                raise BadRequestError(
                    message="Cannot share with someone outside this organization", details={}
                )
            grant = await resource_grant_repo.upsert(
                self.db,
                organization_id=ctx.organization_id,
                subject_user_id=data.subject_user_id,
                resource_type=RECORD_RESOURCE,
                resource_id=record_id,
                level=level,
                created_by_user_id=ctx.user_id,
                expires_at=expires_at,
                clear_expiry="expires_at" in data.model_fields_set and expires_at is None,
            )
        else:
            assert data.subject_group_id is not None
            assert expires_at is not None
            group = await group_repo.get(
                self.db, organization_id=ctx.organization_id, group_id=data.subject_group_id
            )
            if group is None:
                raise BadRequestError(
                    message="Cannot share with a group outside this organization", details={}
                )
            grant = await resource_grant_repo.upsert_for_group(
                self.db,
                organization_id=ctx.organization_id,
                subject_group_id=data.subject_group_id,
                resource_type=RECORD_RESOURCE,
                resource_id=record_id,
                level=level,
                created_by_user_id=ctx.user_id,
                expires_at=expires_at,
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="table.record_access_changed",
            target_type=RECORD_RESOURCE,
            target_id=str(record_id),
            details={
                "table_id": str(table_id),
                "level": data.level,
                "subject_user_id": str(data.subject_user_id) if data.subject_user_id else None,
                "subject_group_id": str(data.subject_group_id) if data.subject_group_id else None,
                "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            },
        )
        return await self._access_read(ctx, table_id, record_id)

    async def revoke_record_grant(
        self,
        ctx: AuthContext,
        table_id: UUID,
        record_id: UUID,
        subject_id: UUID,
        *,
        kind: Literal["user", "group"],
    ) -> None:
        """Remove only the named row grant; current membership and policy still govern access."""
        await self._access_record(ctx, table_id, record_id, lock=True)
        if kind == "user":
            await resource_grant_repo.revoke(
                self.db,
                organization_id=ctx.organization_id,
                subject_user_id=subject_id,
                resource_type=RECORD_RESOURCE,
                resource_id=record_id,
            )
        else:
            await resource_grant_repo.revoke_for_group(
                self.db,
                organization_id=ctx.organization_id,
                subject_group_id=subject_id,
                resource_type=RECORD_RESOURCE,
                resource_id=record_id,
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="table.record_access_revoked",
            target_type=RECORD_RESOURCE,
            target_id=str(record_id),
            details={"table_id": str(table_id), "subject_id": str(subject_id), "kind": kind},
        )
