"""Virtual Tables: tables, schema versions, records, history, receipts, outbox (#1782).

A virtual table is metadata plus JSONB rather than a physical SQL table: a tenant
creating one must not put DDL on the request path, and renaming a column must not
be a migration. So the shape of a table is a row per schema version in
`virtual_table_schema_versions`, records are JSONB keyed by column id in
`virtual_table_records`, and nothing else in the schema ever changes.

Decisions worth knowing when reading the constraints:

- `virtual_table_records` is unique on `(table_id, external_id)` where
  `external_id IS NOT NULL`. That partial index is what an upsert races against,
  so two concurrent upserts of one external id cannot both insert.
- `virtual_table_record_history.record_id` has no foreign key: a hard delete
  removes the record and must leave its history behind.
- `virtual_table_receipts` is unique on `(organization_id, principal_id, operation,
  operation_key)`. A retried write claims the same row and returns the stored
  outcome instead of writing twice; `payload_hash` refuses a reused key with a
  changed body.
- `virtual_table_outbox` holds `table.record.created` events written in the same
  transaction as the record. The partial index covers only undelivered rows.
- Table names are unique among live tables only, so an archived table's name can
  be reused.

New tables only, so `downgrade()` drops them and loses nothing that existed before.

Revision ID: 0092_virtual_tables
Revises: 0091_rag_metadata_prereqs
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0092_virtual_tables"
down_revision: str | Sequence[str] | None = "0091_rag_metadata_prereqs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "virtual_table_receipts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation IN ('record.create', 'record.update', 'record.delete', 'record.upsert')",
            name=op.f("virtual_table_receipts_operation_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("virtual_table_receipts_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["users.id"],
            name=op.f("virtual_table_receipts_principal_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("virtual_table_receipts_pkey")),
        sa.UniqueConstraint(
            "organization_id",
            "principal_id",
            "operation",
            "operation_key",
            name="uq_virtual_table_receipt_key",
        ),
    )
    op.create_table(
        "virtual_tables",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "visibility IN ('private', 'team', 'org')", name=op.f("virtual_tables_visibility_check")
        ),
        sa.CheckConstraint("schema_version >= 1", name=op.f("virtual_tables_schema_version_check")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("virtual_tables_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("virtual_tables_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("virtual_tables_pkey")),
    )
    op.create_index(
        "uq_virtual_table_org_name",
        "virtual_tables",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        op.f("virtual_tables_organization_id_idx"),
        "virtual_tables",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("virtual_tables_owner_user_id_idx"), "virtual_tables", ["owner_user_id"], unique=False
    )
    op.create_table(
        "virtual_table_outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("table_id", sa.UUID(), nullable=False),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "event_type IN ('table.record.created')",
            name=op.f("virtual_table_outbox_event_type_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("virtual_table_outbox_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["virtual_tables.id"],
            name=op.f("virtual_table_outbox_table_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("virtual_table_outbox_pkey")),
    )
    op.create_index(
        "virtual_table_outbox_pending_idx",
        "virtual_table_outbox",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    op.create_table(
        "virtual_table_record_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("table_id", sa.UUID(), nullable=False),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation IN ('create', 'update', 'delete')",
            name=op.f("virtual_table_record_history_operation_check"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("virtual_table_record_history_actor_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("virtual_table_record_history_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["virtual_tables.id"],
            name=op.f("virtual_table_record_history_table_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("virtual_table_record_history_pkey")),
    )
    op.create_index(
        "virtual_table_record_history_record_idx",
        "virtual_table_record_history",
        ["record_id", "revision"],
        unique=False,
    )
    op.create_table(
        "virtual_table_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("table_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("revision >= 1", name=op.f("virtual_table_records_revision_check")),
        sa.CheckConstraint(
            "schema_version >= 1", name=op.f("virtual_table_records_schema_version_check")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("virtual_table_records_created_by_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("virtual_table_records_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["virtual_tables.id"],
            name=op.f("virtual_table_records_table_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("virtual_table_records_updated_by_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("virtual_table_records_pkey")),
    )
    op.create_index(
        "uq_virtual_table_record_external_id",
        "virtual_table_records",
        ["table_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "virtual_table_records_table_created_idx",
        "virtual_table_records",
        ["table_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "virtual_table_schema_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("table_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("virtual_table_schema_versions_version_check")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("virtual_table_schema_versions_created_by_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["virtual_tables.id"],
            name=op.f("virtual_table_schema_versions_table_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("virtual_table_schema_versions_pkey")),
        sa.UniqueConstraint("table_id", "version", name="uq_virtual_table_schema_version"),
    )


def downgrade() -> None:
    op.drop_table("virtual_table_schema_versions")
    op.drop_index("virtual_table_records_table_created_idx", table_name="virtual_table_records")
    op.drop_index(
        "uq_virtual_table_record_external_id",
        table_name="virtual_table_records",
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.drop_table("virtual_table_records")
    op.drop_index(
        "virtual_table_record_history_record_idx", table_name="virtual_table_record_history"
    )
    op.drop_table("virtual_table_record_history")
    op.drop_index(
        "virtual_table_outbox_pending_idx",
        table_name="virtual_table_outbox",
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    op.drop_table("virtual_table_outbox")
    op.drop_index(op.f("virtual_tables_owner_user_id_idx"), table_name="virtual_tables")
    op.drop_index(op.f("virtual_tables_organization_id_idx"), table_name="virtual_tables")
    op.drop_index(
        "uq_virtual_table_org_name",
        table_name="virtual_tables",
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.drop_table("virtual_tables")
    op.drop_table("virtual_table_receipts")
