"""Local services become service connections, and a connection may carry a vault key.

`local_services` (#1604) was keyless because its first two users, Ollama and the
LiteParse OCR sidecar, sit on the deployment's own network, and because the vault is
per organization (#1631). #1632 then asked for an OpenAI-compatible `/embeddings`
endpoint that wants a key. The table is renamed rather than copied, so every row, and
every knowledge base naming one, survives untouched, and it gains:

- `secret_id`, the organization's vault key (`ON DELETE SET NULL`, indexed), and
- `requires_key`, which outlives the key: a connection whose secret was deleted
  reads as missing its key instead of as a keyless endpoint.

A CHECK keeps a deployment-owned row (no organization) keyless, since the vault has
no deployment scope to hold its key. Postgres cuts identifiers at 63 characters, so
the naming convention's `service_connections_ck_service_connections_deployment_keyless_check`
is stored as `service_connections_ck_service_connections_deployment_k_44ad`; the
downgrade names it that way.

`knowledge_bases_embedding_endpoint_id_fkey` follows the table by OID through the
rename and needs no statement. The constraint and index names were read from a
database at `0364_merge_routine_and_kb`, not assumed.

Downgrading drops every connection key and the `requires_key` flag, and leaves any
`openai_compatible` row in place, which the previous build does not recognise.

Revision ID: 0365_service_connections
Revises: 0364_merge_routine_and_kb
Create Date: 2026-11-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0365_service_connections"
down_revision: str | None = "0364_merge_routine_and_kb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_RENAMES = (
    ("local_services_pkey", "service_connections_pkey"),
    (
        "local_services_created_by_user_id_fkey",
        "service_connections_created_by_user_id_fkey",
    ),
    ("local_services_organization_id_fkey", "service_connections_organization_id_fkey"),
    (
        "local_services_ck_local_services_kind_check",
        "service_connections_ck_service_connections_kind_check",
    ),
)


def upgrade() -> None:
    op.rename_table("local_services", "service_connections")
    for old, new in _CONSTRAINT_RENAMES:
        op.execute(f'ALTER TABLE service_connections RENAME CONSTRAINT "{old}" TO "{new}"')
    op.execute(
        "ALTER INDEX local_services_organization_id_idx "
        "RENAME TO service_connections_organization_id_idx"
    )
    op.add_column(
        "service_connections",
        sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "service_connections_secret_id_fkey",
        "service_connections",
        "organization_secrets",
        ["secret_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "service_connections_secret_id_idx", "service_connections", ["secret_id"], unique=False
    )
    op.add_column(
        "service_connections",
        sa.Column("requires_key", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        "ck_service_connections_deployment_keyless",
        "service_connections",
        "organization_id IS NOT NULL OR secret_id IS NULL",
    )


def downgrade() -> None:
    # Raw SQL: `drop_constraint` would run the stored name through the naming
    # convention a second time.
    op.execute(
        "ALTER TABLE service_connections "
        "DROP CONSTRAINT service_connections_ck_service_connections_deployment_k_44ad"
    )
    op.drop_column("service_connections", "requires_key")
    op.drop_index("service_connections_secret_id_idx", table_name="service_connections")
    op.drop_constraint(
        "service_connections_secret_id_fkey", "service_connections", type_="foreignkey"
    )
    op.drop_column("service_connections", "secret_id")
    op.execute(
        "ALTER INDEX service_connections_organization_id_idx "
        "RENAME TO local_services_organization_id_idx"
    )
    for old, new in reversed(_CONSTRAINT_RENAMES):
        op.execute(f'ALTER TABLE service_connections RENAME CONSTRAINT "{new}" TO "{old}"')
    op.rename_table("service_connections", "local_services")
