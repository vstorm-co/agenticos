"""Authoring proposals: the assistant's requests, and the spec changes it proposes.

`authoring_requests` is one Improve or Verify a person started on an agent or a
skill. `spec_proposal_batches` is what one request proposed for an agent's
draft, at most one open per agent; `spec_proposal_hunks` is each change in it,
decided on its own.

`skill_proposals` gains the columns an evidence-backed proposal needs - the
version it was written against, its rationale and checked evidence, the effect
it expects and the request that produced it. All are nullable or defaulted, so
the proposals an agent's workspace has already written keep applying as before.

`eval_runs.excluded_case_ids` lists the cases a check leaves out because they
were taken from the proposal's own evidence; existing runs excluded nothing.
`eval_run_arms.skill_bodies` holds the proposed skill bodies a candidate serves
when a run checks a skill change; existing arms served none.

`ck_agent_kind` gains `improver`, and states every kind the milestone defines,
so the constraint is the same whichever order the kinds' migrations land in.

The downgrade drops the tables and columns and loses every proposal batch and
request; skill proposals stay, as they were. The improver stays too, as an
ordinary agent - `kind` back to `agent` and its `system_key` cleared, as the
other system agents' migrations do - so the narrower constraint holds and
nothing anybody edited is deleted; upgrading again seeds a fresh improver.

Revision ID: 0152_authoring_proposals
Revises: 0149_knowledge_gaps
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0152_authoring_proposals"
down_revision: str | None = "0149_knowledge_gaps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('agent', 'judge', 'drafter', 'generator', 'improver')"
_KINDS_BEFORE = "kind IN ('agent', 'judge', 'drafter')"


def upgrade() -> None:
    op.create_table(
        "authoring_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("skill_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("estimate_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("run_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('improve', 'verify')",
            name=op.f("authoring_requests_ck_authoring_request_kind_check"),
        ),
        sa.CheckConstraint(
            "(target = 'agent' AND agent_id IS NOT NULL AND skill_id IS NULL) OR "
            "(target = 'skill' AND skill_id IS NOT NULL AND agent_id IS NULL)",
            name=op.f("authoring_requests_ck_authoring_request_target_check"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name=op.f("authoring_requests_ck_authoring_request_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("authoring_requests_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("authoring_requests_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("authoring_requests_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name=op.f("authoring_requests_skill_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("authoring_requests_pkey")),
    )
    op.create_index(
        op.f("authoring_requests_organization_id_idx"),
        "authoring_requests",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_authoring_requests_agent",
        "authoring_requests",
        ["organization_id", "agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_authoring_requests_skill",
        "authoring_requests",
        ["organization_id", "skill_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "spec_proposal_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("source_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expected_effect", sa.Text(), nullable=False),
        sa.Column(
            "evidence_conversation_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "check_eval_run_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'superseded', 'published')",
            name=op.f("spec_proposal_batches_ck_spec_proposal_batch_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("spec_proposal_batches_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("spec_proposal_batches_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["authoring_requests.id"],
            name=op.f("spec_proposal_batches_request_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("spec_proposal_batches_pkey")),
    )
    op.create_index(
        op.f("spec_proposal_batches_organization_id_idx"),
        "spec_proposal_batches",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_spec_proposal_batches_agent",
        "spec_proposal_batches",
        ["organization_id", "agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_spec_proposal_batches_open",
        "spec_proposal_batches",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "spec_proposal_hunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("base_start", sa.Integer(), nullable=True),
        sa.Column("base_end", sa.Integer(), nullable=True),
        sa.Column("context_before", sa.Text(), nullable=False),
        sa.Column("context_after", sa.Text(), nullable=False),
        sa.Column("old_text", sa.Text(), nullable=False),
        sa.Column("new_text", sa.Text(), nullable=False),
        sa.Column("accepted_text", sa.Text(), nullable=True),
        sa.Column("capability_id", sa.String(length=64), nullable=True),
        sa.Column("tool_id", sa.String(length=128), nullable=True),
        sa.Column("base_name", sa.String(length=64), nullable=True),
        sa.Column("base_description", sa.Text(), nullable=True),
        sa.Column("new_name", sa.String(length=64), nullable=True),
        sa.Column("new_description", sa.Text(), nullable=True),
        sa.Column("accepted_override", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_dropped", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('instructions', 'tool_override')",
            name=op.f("spec_proposal_hunks_ck_spec_proposal_hunk_kind_check"),
        ),
        sa.CheckConstraint(
            "origin IN ('improve', 'verify')",
            name=op.f("spec_proposal_hunks_ck_spec_proposal_hunk_origin_check"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'dismissed')",
            name=op.f("spec_proposal_hunks_ck_spec_proposal_hunk_status_check"),
        ),
        sa.CheckConstraint(
            "kind <> 'tool_override' OR (capability_id IS NOT NULL AND tool_id IS NOT NULL)",
            name=op.f("spec_proposal_hunks_ck_spec_proposal_hunk_tool_check"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["spec_proposal_batches.id"],
            name=op.f("spec_proposal_hunks_batch_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("spec_proposal_hunks_decided_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("spec_proposal_hunks_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("spec_proposal_hunks_pkey")),
    )
    op.create_index(
        op.f("spec_proposal_hunks_batch_id_idx"), "spec_proposal_hunks", ["batch_id"], unique=False
    )
    op.create_index(
        op.f("spec_proposal_hunks_organization_id_idx"),
        "spec_proposal_hunks",
        ["organization_id"],
        unique=False,
    )

    op.add_column("skill_proposals", sa.Column("base_version", sa.Integer(), nullable=True))
    op.add_column(
        "skill_proposals",
        sa.Column("rationale", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "skill_proposals",
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "skill_proposals",
        sa.Column("evidence_dropped", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "skill_proposals",
        sa.Column("expected_effect", sa.Text(), server_default="", nullable=False),
    )
    op.add_column("skill_proposals", sa.Column("authoring_request_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("skill_proposals_authoring_request_id_fkey"),
        "skill_proposals",
        "authoring_requests",
        ["authoring_request_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "eval_runs",
        sa.Column(
            "excluded_case_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False
        ),
    )
    op.add_column(
        "eval_run_arms",
        sa.Column("skill_bodies", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.create_check_constraint("ck_agent_kind", "agents", _KINDS)


def downgrade() -> None:
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.execute("UPDATE agents SET kind = 'agent', system_key = NULL WHERE kind = 'improver'")
    op.create_check_constraint("ck_agent_kind", "agents", _KINDS_BEFORE)

    op.drop_column("eval_run_arms", "skill_bodies")
    op.drop_column("eval_runs", "excluded_case_ids")

    op.drop_constraint(
        op.f("skill_proposals_authoring_request_id_fkey"), "skill_proposals", type_="foreignkey"
    )
    op.drop_column("skill_proposals", "authoring_request_id")
    op.drop_column("skill_proposals", "expected_effect")
    op.drop_column("skill_proposals", "evidence_dropped")
    op.drop_column("skill_proposals", "evidence")
    op.drop_column("skill_proposals", "rationale")
    op.drop_column("skill_proposals", "base_version")

    op.drop_index(op.f("spec_proposal_hunks_organization_id_idx"), table_name="spec_proposal_hunks")
    op.drop_index(op.f("spec_proposal_hunks_batch_id_idx"), table_name="spec_proposal_hunks")
    op.drop_table("spec_proposal_hunks")

    op.drop_index(
        "uq_spec_proposal_batches_open",
        table_name="spec_proposal_batches",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.drop_index("ix_spec_proposal_batches_agent", table_name="spec_proposal_batches")
    op.drop_index(
        op.f("spec_proposal_batches_organization_id_idx"), table_name="spec_proposal_batches"
    )
    op.drop_table("spec_proposal_batches")

    op.drop_index("ix_authoring_requests_skill", table_name="authoring_requests")
    op.drop_index("ix_authoring_requests_agent", table_name="authoring_requests")
    op.drop_index(op.f("authoring_requests_organization_id_idx"), table_name="authoring_requests")
    op.drop_table("authoring_requests")
