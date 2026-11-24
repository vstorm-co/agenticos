"""Typed browser plans and explicit named shared-account policy.

Revision ID: 0342_browser_credential_plans
Revises: 0341_room_task_handoffs

The three existing-table tenant keys are built concurrently, then attached in the
same transaction as the new empty tables. A retry accepts only an exact standalone
index; it never drops an unexpected object or interferes with a running build.
Attaching each key still requires a brief table lock. Rehearse and monitor lock
waits before deployment. Downgrade refuses to discard filled-plan evidence or the
policy needed to interpret a shared browser envelope.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0342_browser_credential_plans"
down_revision: str | None = "0341_room_task_handoffs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = (
    ("agents", "uq_agents_org_id"),
    ("agent_runs", "uq_agent_runs_org_id"),
    ("organization_secrets", "uq_organization_secrets_org_id"),
)


def _building(table: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_progress_create_index p "
                "JOIN pg_locks l ON l.pid = p.pid "
                "WHERE p.pid <> pg_backend_pid() AND l.locktype = 'relation' "
                "AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                "AND l.relation = to_regclass(:table))"
            ),
            {"table": table},
        )
    )


def _index_state(table: str, name: str) -> tuple[bool, bool] | None:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT CASE WHEN c.relkind = 'i' THEN "
                "i.indrelid = to_regclass(:table) AND i.indisunique AND i.indimmediate "
                "AND NOT i.indisprimary AND NOT i.indisexclusion AND NOT i.indnullsnotdistinct "
                "AND i.indnkeyatts = 2 AND i.indnatts = 2 "
                "AND i.indexprs IS NULL AND i.indpred IS NULL AND a.amname = 'btree' "
                "AND i.indoption[0] = 0 AND i.indoption[1] = 0 "
                "AND i.indcollation[0] = 0 AND i.indcollation[1] = 0 "
                "AND i.indclass[0] = i.indclass[1] "
                "AND EXISTS (SELECT 1 FROM pg_opclass o WHERE o.oid = i.indclass[0] "
                "AND o.opcmethod = a.oid AND o.opcnamespace = 'pg_catalog'::regnamespace "
                "AND o.opcname = 'uuid_ops' AND o.opcintype = 'uuid'::regtype AND o.opcdefault) "
                "AND pg_get_indexdef(c.oid, 1, false) = 'organization_id' "
                "AND pg_get_indexdef(c.oid, 2, false) = 'id' "
                "AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = c.oid) "
                "ELSE false END AS expected, "
                "i.indisvalid AND i.indisready AND i.indislive AS usable "
                "FROM pg_class c LEFT JOIN pg_index i ON i.indexrelid = c.oid "
                "LEFT JOIN pg_am a ON a.oid = c.relam WHERE c.oid = to_regclass(:name)"
            ),
            {"table": table, "name": name},
        )
        .one_or_none()
    )
    return None if row is None else (bool(row.expected), bool(row.usable))


def _check(table: str, name: str) -> tuple[bool, bool] | None:
    if _building(table):
        raise RuntimeError(
            f"An index on {table} is being built; let it finish before revision 0342."
        )
    state = _index_state(table, name)
    if state is not None and not state[0]:
        raise RuntimeError(
            f"Existing {name} is not the expected standalone tenant key; reconcile it before revision 0342."
        )
    return state


def _tenant_keys() -> None:
    for table, name in _KEYS:
        _check(table, name)
    with op.get_context().autocommit_block():
        for table, name in _KEYS:
            state = _check(table, name)
            if state is not None and state[1]:
                continue
            if state is not None:
                op.drop_index(name, table_name=table, postgresql_concurrently=True)
            op.create_index(
                name, table, ["organization_id", "id"], unique=True, postgresql_concurrently=True
            )
    for table, name in _KEYS:
        # Identifiers are the static revision-owned names above, never request data.
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE USING INDEX {name}")


def upgrade() -> None:
    _tenant_keys()
    op.create_table(
        "browser_credential_policies",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("secret_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id", "secret_id"],
            ["organization_secrets.organization_id", "organization_secrets.id"],
            name="fk_browser_policy_secret",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "secret_id"),
    )
    op.create_table(
        "browser_credential_agent_grants",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("secret_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "secret_id"],
            [
                "browser_credential_policies.organization_id",
                "browser_credential_policies.secret_id",
            ],
            name="fk_browser_agent_grant_policy",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            name="fk_browser_agent_grant_agent",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "secret_id", "agent_id"),
    )
    op.create_table(
        "browser_credential_member_grants",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("secret_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "secret_id"],
            [
                "browser_credential_policies.organization_id",
                "browser_credential_policies.secret_id",
            ],
            name="fk_browser_member_grant_policy",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            name="fk_browser_member_grant_member",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "secret_id", "user_id"),
    )
    op.create_table(
        "browser_credential_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("secret_id", sa.UUID(), nullable=False),
        sa.Column("authorization_generation", sa.UUID(), nullable=False),
        sa.Column("controller_id", sa.UUID(), nullable=False),
        sa.Column("tab_id", sa.String(200), nullable=False),
        sa.Column("call_id", sa.String(200), nullable=False),
        sa.Column("operation", sa.String(16), server_default="fill", nullable=False),
        sa.Column("parent_plan_id", sa.UUID(), nullable=True),
        sa.Column("selection", postgresql.JSONB(), nullable=False),
        sa.Column("observation", postgresql.JSONB(), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column(
            "output_protected", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_browser_plans_org_id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id", "parent_plan_id"],
            ["browser_credential_plans.organization_id", "browser_credential_plans.id"],
            name="fk_browser_plan_parent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["agent_runs.organization_id", "agent_runs.id"],
            name="fk_browser_plan_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            name="fk_browser_plan_agent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            name="fk_browser_plan_member",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "secret_id"],
            ["organization_secrets.organization_id", "organization_secrets.id"],
            name="fk_browser_plan_secret",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(operation = 'fill' AND parent_plan_id IS NULL) OR (operation = 'submit' AND parent_plan_id IS NOT NULL)",
            name=op.f("browser_credential_plans_ck_browser_plan_operation_check"),
        ),
        sa.CheckConstraint(
            "state IN ('requested', 'preparing', 'awaiting_confirmation', 'approved', 'claimed', "
            "'filled', 'submitted', 'refused', 'unknown', 'expired', 'declined')",
            name=op.f("browser_credential_plans_ck_browser_plan_state_check"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('awaiting_confirmation', 'approved', 'claimed', 'filled', 'submitted') OR observation IS NOT NULL",
            name=op.f("browser_credential_plans_ck_browser_plan_observation_check"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('claimed', 'filled', 'submitted') OR "
            "(attempt_id IS NOT NULL AND claimed_at IS NOT NULL AND output_protected)",
            name=op.f("browser_credential_plans_ck_browser_plan_claim_check"),
        ),
    )
    op.create_index(
        "ix_browser_plans_owner_run",
        "browser_credential_plans",
        ["organization_id", "user_id", "run_id"],
    )
    op.create_index(
        "uq_browser_plan_submission",
        "browser_credential_plans",
        ["organization_id", "parent_plan_id"],
        unique=True,
        postgresql_where=sa.text("parent_plan_id IS NOT NULL"),
    )
    op.create_index(
        "uq_browser_plans_active_view",
        "browser_credential_plans",
        ["organization_id", "run_id", "call_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('requested', 'preparing', 'awaiting_confirmation', 'approved', 'claimed')"
        ),
    )


def downgrade() -> None:
    occupied = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM browser_credential_policies) "
            "OR EXISTS (SELECT 1 FROM browser_credential_plans)"
        )
    )
    if occupied:
        raise RuntimeError(
            "Cannot discard browser credential policy or plan evidence; retain a matching application "
            "or restore a matching pre-upgrade backup."
        )
    op.drop_table("browser_credential_plans")
    op.drop_table("browser_credential_member_grants")
    op.drop_table("browser_credential_agent_grants")
    op.drop_table("browser_credential_policies")
    for table, name in reversed(_KEYS):
        # Static revision-owned names; a key already gone must not block the downgrade.
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
