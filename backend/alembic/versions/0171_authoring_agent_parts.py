"""Authoring agent parts: spec field proposals, context proposals, context checks.

`spec_proposal_hunks` gains the columns a `spec_field` hunk needs - the field's
path in the spec, what it does there, and the values it was written against,
proposes and was accepted as, the effect measured on recent runs and the effect
the change predicts - and the kind check gains `spec_field`. Every existing hunk is an instruction or a tool
override and keeps working as before.

`authoring_requests.context_id` is the context file an Improve was asked for, and
the target check gains `context`. `context_proposals` holds what the assistant
proposed for a context file, decided whole like a skill proposal.
`eval_run_arms.context_bodies` holds the proposed context bodies a candidate
serves when a run checks a context change; existing arms served none.

The downgrade deletes every spec field hunk, every context request and every
context proposal before narrowing the checks they would break, then drops the
columns and the table.

Revision ID: 0171_authoring_agent_parts
Revises: 0170_promotion_gate
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0171_authoring_agent_parts"
down_revision: str | None = "0170_promotion_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HUNK_KINDS = "kind IN ('instructions', 'tool_override', 'spec_field')"
_HUNK_KINDS_BEFORE = "kind IN ('instructions', 'tool_override')"
_TARGETS = (
    "(target = 'agent' AND agent_id IS NOT NULL AND skill_id IS NULL "
    "AND context_id IS NULL) OR "
    "(target = 'skill' AND skill_id IS NOT NULL AND agent_id IS NULL "
    "AND context_id IS NULL) OR "
    "(target = 'context' AND context_id IS NOT NULL AND agent_id IS NULL "
    "AND skill_id IS NULL)"
)
_TARGETS_BEFORE = (
    "(target = 'agent' AND agent_id IS NOT NULL AND skill_id IS NULL) OR "
    "(target = 'skill' AND skill_id IS NOT NULL AND agent_id IS NULL)"
)
_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("spec_proposal_hunks", sa.Column("path", sa.String(length=200), nullable=True))
    op.add_column("spec_proposal_hunks", sa.Column("op", sa.String(length=8), nullable=True))
    for column in ("base_value", "new_value", "accepted_value", "effect"):
        op.add_column("spec_proposal_hunks", sa.Column(column, _JSONB, nullable=True))
    op.add_column(
        "spec_proposal_hunks",
        sa.Column("expected_effect", sa.Text(), nullable=False, server_default=""),
    )
    op.drop_constraint("ck_spec_proposal_hunk_kind", "spec_proposal_hunks", type_="check")
    op.create_check_constraint("ck_spec_proposal_hunk_kind", "spec_proposal_hunks", _HUNK_KINDS)
    op.create_check_constraint(
        "ck_spec_proposal_hunk_field",
        "spec_proposal_hunks",
        "kind <> 'spec_field' OR (path IS NOT NULL AND op IN ('set', 'add', 'remove'))",
    )

    op.add_column("authoring_requests", sa.Column("context_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "authoring_requests_context_id_fkey",
        "authoring_requests",
        "context_files",
        ["context_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_authoring_requests_context",
        "authoring_requests",
        ["organization_id", "context_id", "created_at"],
    )
    op.drop_constraint("ck_authoring_request_target", "authoring_requests", type_="check")
    op.create_check_constraint("ck_authoring_request_target", "authoring_requests", _TARGETS)

    op.create_table(
        "context_proposals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("context_id", sa.UUID(), nullable=False),
        sa.Column("base_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence", _JSONB, nullable=False),
        sa.Column("evidence_dropped", sa.Integer(), nullable=False),
        sa.Column("expected_effect", sa.Text(), nullable=False),
        sa.Column("authoring_request_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["authoring_request_id"], ["authoring_requests.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["context_id"], ["context_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("context_proposals_context_id_idx", "context_proposals", ["context_id"])
    op.create_index(
        "context_proposals_organization_id_idx", "context_proposals", ["organization_id"]
    )
    op.create_index("context_proposals_status_idx", "context_proposals", ["status"])
    op.create_index(
        "ix_context_proposals_pending", "context_proposals", ["organization_id", "status"]
    )

    op.add_column("eval_run_arms", sa.Column("context_bodies", _JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("eval_run_arms", "context_bodies")
    op.drop_table("context_proposals")

    op.execute("DELETE FROM authoring_requests WHERE target = 'context'")
    op.drop_constraint("ck_authoring_request_target", "authoring_requests", type_="check")
    op.create_check_constraint("ck_authoring_request_target", "authoring_requests", _TARGETS_BEFORE)
    op.drop_index("ix_authoring_requests_context", table_name="authoring_requests")
    op.drop_constraint(
        "authoring_requests_context_id_fkey", "authoring_requests", type_="foreignkey"
    )
    op.drop_column("authoring_requests", "context_id")

    op.execute("DELETE FROM spec_proposal_hunks WHERE kind = 'spec_field'")
    op.drop_constraint("ck_spec_proposal_hunk_field", "spec_proposal_hunks", type_="check")
    op.drop_constraint("ck_spec_proposal_hunk_kind", "spec_proposal_hunks", type_="check")
    op.create_check_constraint(
        "ck_spec_proposal_hunk_kind", "spec_proposal_hunks", _HUNK_KINDS_BEFORE
    )
    for column in (
        "expected_effect",
        "effect",
        "accepted_value",
        "new_value",
        "base_value",
        "op",
        "path",
    ):
        op.drop_column("spec_proposal_hunks", column)
