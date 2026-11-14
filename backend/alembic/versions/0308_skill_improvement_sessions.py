"""Skill improvement sessions: Improve run on one line of a shared skill.

An agent's improvement session (`improvement_runs`) belongs to one agent, its
draft and one dataset. A skill has no single agent - its main line or one of its
forks serves several - so a session on a skill gets its own pair of tables rather
than nullable agent columns on the agent's: `skill_improvement_runs`, one session
per line with at most one open (main's null fork counts as one line, hence
`NULLS NOT DISTINCT`), and `skill_improvement_iterations`, one attempt each.
A session's `purpose` is improving the line, or - for catching up - taking main
into a fork, or a fork (`source_fork_id`) into main.
Statuses, stages and stop reasons are the agent session's values.

The edits a session proposes reuse the authoring tables:

- `authoring_requests` gains the `analyze` kind - grouping a skill's bad answers into
  problems without proposing, the session's Understand step - and
  `skill_improvement_run_id`.
- `spec_proposal_batches` may hold a skill line's candidate: `agent_id` becomes
  nullable and a batch names either an agent, or a skill, its fork, the version its
  edits are anchored on and its session.
- `spec_proposal_hunks` gains `skill_body` and `skill_description`.

**Downgrade** deletes the skill sessions, their batches, hunks and analysis
requests, which only exist with these tables.

Revision ID: 0308_skill_improvement_sessions
Revises: 0307_skill_checks
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0308_skill_improvement_sessions"
down_revision: str | Sequence[str] | None = "0307_skill_checks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HUNK_KINDS_BEFORE = "'instructions', 'tool_override', 'spec_field', 'create_skill'"

_BATCH_TARGET = (
    "(agent_id IS NOT NULL AND skill_id IS NULL AND fork_id IS NULL "
    "AND skill_improvement_run_id IS NULL) OR "
    "(agent_id IS NULL AND skill_id IS NOT NULL AND skill_improvement_run_id IS NOT NULL "
    "AND base_skill_version_id IS NOT NULL AND status IN ('candidate', 'superseded'))"
)


def _kinds(hunks: str, requests: str) -> None:
    op.drop_constraint("ck_spec_proposal_hunk_kind", "spec_proposal_hunks", type_="check")
    op.create_check_constraint(
        "ck_spec_proposal_hunk_kind", "spec_proposal_hunks", f"kind IN ({hunks})"
    )
    op.drop_constraint("ck_authoring_request_kind", "authoring_requests", type_="check")
    op.create_check_constraint(
        "ck_authoring_request_kind", "authoring_requests", f"kind IN ({requests})"
    )


def upgrade() -> None:
    op.create_table(
        "skill_improvement_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("fork_id", sa.UUID(), nullable=True),
        sa.Column("purpose", sa.String(length=16), server_default="improve", nullable=False),
        sa.Column("source_fork_id", sa.UUID(), nullable=True),
        sa.Column("base_version_id", sa.UUID(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_by_api_key_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_api_key_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column(
            "seed", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("analysis_request_id", sa.UUID(), nullable=True),
        sa.Column("estimate_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("budget_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("best_iteration_id", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("applied_version_id", sa.UUID(), nullable=True),
        sa.Column("stop_reason", sa.String(length=16), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("stage_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('applied', 'applied_pinned', 'forked', 'discarded', "
            "'caught_up', 'returned_to_main')",
            name=op.f("skill_improvement_runs_ck_skill_improvement_run_outcome_check"),
        ),
        sa.CheckConstraint(
            "stage IS NULL OR stage IN ('analyzing', 'classifying', 'proposing', 'filtering', 'evaluating', 'judging')",
            name=op.f("skill_improvement_runs_ck_skill_improvement_run_stage_check"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting', 'ready', 'stopped', 'failed', 'cancelled', 'stale', 'accepted', 'published', 'rejected')",
            name=op.f("skill_improvement_runs_ck_skill_improvement_run_status_check"),
        ),
        sa.CheckConstraint(
            "stop_reason IS NULL OR stop_reason IN ('no_data', 'no_proposal', 'budget', 'inconclusive', 'regression', 'no_change', 'max_iterations', 'repeat_candidate', 'permission', 'stale', 'stalled', 'proposal', 'eval', 'superseded', 'knowledge_only', 'draft', 'expired')",
            name=op.f("skill_improvement_runs_ck_skill_improvement_run_stop_reason_check"),
        ),
        sa.CheckConstraint(
            "estimate_usd >= 0 AND budget_usd >= 0",
            name=op.f("skill_improvement_runs_ck_skill_improvement_run_money_check"),
        ),
        sa.CheckConstraint(
            "max_iterations BETWEEN 1 AND 10 AND iteration BETWEEN 1 AND max_iterations",
            name=op.f("skill_improvement_runs_ck_skill_improvement_run_iterations_check"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("skill_improvement_runs_actor_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("skill_improvement_runs_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fork_id", "organization_id"],
            ["skill_forks.id", "skill_forks.organization_id"],
            name=op.f("skill_improvement_runs_fork_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_fork_id", "organization_id"],
            ["skill_forks.id", "skill_forks.organization_id"],
            name=op.f("skill_improvement_runs_source_fork_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "purpose IN ('improve', 'catch_up', 'to_main')",
            name=op.f("skill_improvement_runs_ck_skill_improvement_run_purpose_check"),
        ),
        sa.CheckConstraint(
            "(purpose = 'to_main') = (fork_id IS NULL AND source_fork_id IS NOT NULL) "
            "AND (purpose = 'to_main' OR source_fork_id IS NULL)",
            name=op.f("skill_improvement_runs_ck_skill_improvement_run_source_fork_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("skill_improvement_runs_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            name=op.f("skill_improvement_runs_skill_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("skill_improvement_runs_pkey")),
        sa.UniqueConstraint("id", "organization_id", name="uq_skill_improvement_runs_tenant"),
    )
    op.create_index(
        "ix_skill_improvement_runs_skill",
        "skill_improvement_runs",
        ["organization_id", "skill_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_skill_improvement_runs_unsettled",
        "skill_improvement_runs",
        ["status"],
        unique=False,
        postgresql_where=sa.text(
            "status IN ('queued', 'running', 'waiting', 'ready', 'stopped', 'failed', 'accepted')"
        ),
    )
    op.create_index(
        op.f("skill_improvement_runs_organization_id_idx"),
        "skill_improvement_runs",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "uq_skill_improvement_runs_open",
        "skill_improvement_runs",
        ["skill_id", "fork_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text(
            "status IN ('queued', 'running', 'waiting', 'ready', 'stopped', 'failed')"
        ),
    )
    op.create_table(
        "skill_improvement_iterations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("authoring_request_id", sa.UUID(), nullable=True),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("included_hunk_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column(
            "dropped_hunk_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False
        ),
        sa.Column(
            "dropped", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("candidate_hash", sa.String(length=64), nullable=True),
        sa.Column("description_changed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("skill_check_id", sa.UUID(), nullable=True),
        sa.Column("check_verdict", sa.String(length=16), nullable=True),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "check_verdict IS NULL OR check_verdict IN ('passed', 'blocked', 'no_better', 'needs_ack', 'failed')",
            name=op.f(
                "skill_improvement_iterations_ck_skill_improvement_iteration_check_verdict_check"
            ),
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('better', 'no_change', 'regression', 'inconclusive')",
            name=op.f("skill_improvement_iterations_ck_skill_improvement_iteration_verdict_check"),
        ),
        sa.CheckConstraint(
            "cost_usd >= 0",
            name=op.f("skill_improvement_iterations_ck_skill_improvement_iteration_cost_check"),
        ),
        sa.ForeignKeyConstraint(
            ["authoring_request_id"],
            ["authoring_requests.id"],
            name=op.f("skill_improvement_iterations_authoring_request_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["spec_proposal_batches.id"],
            name=op.f("skill_improvement_iterations_batch_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["skill_check_id"],
            ["skill_checks.id"],
            name=op.f("skill_improvement_iterations_skill_check_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("skill_improvement_iterations_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "organization_id"],
            ["skill_improvement_runs.id", "skill_improvement_runs.organization_id"],
            name=op.f("skill_improvement_iterations_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("skill_improvement_iterations_pkey")),
        sa.UniqueConstraint("run_id", "number", name="uq_skill_improvement_iterations_number"),
    )
    op.create_index(
        op.f("skill_improvement_iterations_organization_id_idx"),
        "skill_improvement_iterations",
        ["organization_id"],
        unique=False,
    )
    # Each table names the other; the second key goes on once both exist.
    op.create_foreign_key(
        op.f("skill_improvement_runs_best_iteration_id_fkey"),
        "skill_improvement_runs",
        "skill_improvement_iterations",
        ["best_iteration_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("skill_improvement_runs_analysis_request_id_fkey"),
        "skill_improvement_runs",
        "authoring_requests",
        ["analysis_request_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "authoring_requests", sa.Column("skill_improvement_run_id", sa.UUID(), nullable=True)
    )
    op.create_index(
        op.f("authoring_requests_skill_improvement_run_id_idx"),
        "authoring_requests",
        ["skill_improvement_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("authoring_requests_skill_improvement_run_id_fkey"),
        "authoring_requests",
        "skill_improvement_runs",
        ["skill_improvement_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("spec_proposal_batches", sa.Column("skill_id", sa.UUID(), nullable=True))
    op.add_column("spec_proposal_batches", sa.Column("fork_id", sa.UUID(), nullable=True))
    op.add_column(
        "spec_proposal_batches", sa.Column("base_skill_version_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "spec_proposal_batches", sa.Column("skill_improvement_run_id", sa.UUID(), nullable=True)
    )
    op.alter_column("spec_proposal_batches", "agent_id", existing_type=sa.UUID(), nullable=True)
    op.create_index(
        op.f("spec_proposal_batches_skill_improvement_run_id_idx"),
        "spec_proposal_batches",
        ["skill_improvement_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("spec_proposal_batches_skill_improvement_run_id_fkey"),
        "spec_proposal_batches",
        "skill_improvement_runs",
        ["skill_improvement_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("spec_proposal_batches_fork_id_fkey"),
        "spec_proposal_batches",
        "skill_forks",
        ["fork_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("spec_proposal_batches_skill_id_fkey"),
        "spec_proposal_batches",
        "skills",
        ["skill_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_spec_proposal_batch_target", "spec_proposal_batches", _BATCH_TARGET
    )
    _kinds(
        f"{_HUNK_KINDS_BEFORE}, 'skill_body', 'skill_description'", "'improve', 'verify', 'analyze'"
    )


def downgrade() -> None:
    op.execute("DELETE FROM spec_proposal_batches WHERE agent_id IS NULL")
    op.execute("DELETE FROM authoring_requests WHERE kind = 'analyze'")
    op.execute("DELETE FROM authoring_requests WHERE skill_improvement_run_id IS NOT NULL")
    _kinds(_HUNK_KINDS_BEFORE, "'improve', 'verify'")
    op.drop_constraint("ck_spec_proposal_batch_target", "spec_proposal_batches", type_="check")
    op.drop_constraint(
        op.f("spec_proposal_batches_skill_id_fkey"), "spec_proposal_batches", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("spec_proposal_batches_fork_id_fkey"), "spec_proposal_batches", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("spec_proposal_batches_skill_improvement_run_id_fkey"),
        "spec_proposal_batches",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("spec_proposal_batches_skill_improvement_run_id_idx"),
        table_name="spec_proposal_batches",
    )
    op.alter_column("spec_proposal_batches", "agent_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("spec_proposal_batches", "skill_improvement_run_id")
    op.drop_column("spec_proposal_batches", "base_skill_version_id")
    op.drop_column("spec_proposal_batches", "fork_id")
    op.drop_column("spec_proposal_batches", "skill_id")
    op.drop_constraint(
        op.f("authoring_requests_skill_improvement_run_id_fkey"),
        "authoring_requests",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("authoring_requests_skill_improvement_run_id_idx"), table_name="authoring_requests"
    )
    op.drop_column("authoring_requests", "skill_improvement_run_id")
    op.drop_constraint(
        op.f("skill_improvement_runs_best_iteration_id_fkey"),
        "skill_improvement_runs",
        type_="foreignkey",
    )
    op.drop_table("skill_improvement_iterations")
    op.drop_table("skill_improvement_runs")
