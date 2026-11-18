"""Add durable protected-session consent and distinguish derived saved-session envelopes.

Published fill/submit and both joined histories retain their identities. Existing
manual sign-ins keep their exact ciphertext, owner scope and behavior. Downgrade
refuses any new consent/effect evidence or derived envelope instead of handing it
to an older ordinary-output reader.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0345_credential_continuations"
down_revision: str = "0344_browser_procedure_teaching"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "browser_sign_ins",
        sa.Column("protection_kind", sa.String(16), nullable=False, server_default="manual"),
    )
    op.create_check_constraint(
        "ck_browser_sign_in_protection",
        "browser_sign_ins",
        "protection_kind IN ('manual', 'credential')",
    )
    op.create_table(
        "browser_credential_continuations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        *(
            sa.Column(name, sa.UUID(), nullable=False)
            for name in (
                "run_id",
                "agent_id",
                "user_id",
                "secret_id",
                "authorization_generation",
                "source_submission_id",
                "source_fill_id",
                "controller_id",
            )
        ),
        sa.Column("source_call_id", sa.String(200), nullable=False),
        sa.Column("source_tab_id", sa.String(200), nullable=False),
        sa.Column("credential_generations", postgresql.JSONB(), nullable=False),
        sa.Column("observation", postgresql.JSONB(), nullable=True),
        sa.Column("confirmation", postgresql.JSONB(), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("output_protected", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("continuation_call_id", sa.String(200), nullable=True),
        sa.Column("continuation_tab_id", sa.String(200), nullable=True),
        sa.Column("saved_sign_in_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_browser_continuations_org_id"),
        sa.UniqueConstraint(
            "organization_id", "source_submission_id", name="uq_browser_continuation_submission"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        *(
            sa.ForeignKeyConstraint(
                ["organization_id", column],
                [f"{parent}.organization_id", f"{parent}.{key}"],
                name=f"fk_browser_continuation_{name}",
                ondelete="CASCADE",
            )
            for column, parent, key, name in (
                ("source_submission_id", "browser_credential_plans", "id", "submission"),
                ("source_fill_id", "browser_credential_plans", "id", "fill"),
                ("run_id", "agent_runs", "id", "run"),
                ("agent_id", "agents", "id", "agent"),
                ("user_id", "organization_members", "user_id", "member"),
                ("secret_id", "organization_secrets", "id", "secret"),
            )
        ),
        sa.CheckConstraint("output_protected", name="ck_browser_continuation_protected"),
        sa.CheckConstraint(
            "state IN ('requested', 'preparing', 'awaiting_confirmation', 'approved', "
            "'claimed', 'continued', 'refused', 'unknown', 'expired', 'declined')",
            name="ck_browser_continuation_state",
        ),
        sa.CheckConstraint(
            "state NOT IN ('awaiting_confirmation', 'approved', 'claimed', 'continued') "
            "OR observation IS NOT NULL",
            name="ck_browser_continuation_observation",
        ),
        sa.CheckConstraint(
            "state NOT IN ('approved', 'claimed', 'continued') OR confirmation IS NOT NULL",
            name="ck_browser_continuation_confirmation",
        ),
        sa.CheckConstraint(
            "state NOT IN ('claimed', 'continued') OR (attempt_id IS NOT NULL AND claimed_at IS NOT NULL)",
            name="ck_browser_continuation_claim",
        ),
        sa.CheckConstraint(
            "state != 'continued' OR (continuation_call_id IS NOT NULL AND "
            "continuation_tab_id IS NOT NULL AND continuation_call_id != source_call_id AND "
            "continuation_tab_id != source_tab_id AND finished_at IS NOT NULL)",
            name="ck_browser_continuation_identity",
        ),
    )
    op.create_index(
        "ix_browser_continuations_owner_run",
        "browser_credential_continuations",
        ["organization_id", "user_id", "run_id"],
    )
    op.create_index(
        "uq_browser_continuations_active_view",
        "browser_credential_continuations",
        ["organization_id", "run_id", "source_call_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('requested', 'preparing', 'awaiting_confirmation', 'approved', 'claimed')"
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "LOCK TABLE browser_credential_continuations, browser_sign_ins IN ACCESS EXCLUSIVE MODE"
    )
    used = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM browser_credential_continuations) OR "
            "EXISTS (SELECT 1 FROM browser_sign_ins WHERE protection_kind != 'manual')"
        )
    )
    if used:
        raise RuntimeError("Cannot discard protected continuation or saved-session evidence")
    op.drop_table("browser_credential_continuations")
    op.drop_constraint("ck_browser_sign_in_protection", "browser_sign_ins", type_="check")
    op.drop_column("browser_sign_ins", "protection_kind")
