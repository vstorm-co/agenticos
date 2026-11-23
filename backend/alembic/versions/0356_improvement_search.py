"""Let an Improve attempt search many variants of an agent's instructions.

`improvement_runs.mode` says how a session's attempts reach their candidate:
`steps`, one proposal per attempt as before, or `search`, many variants scored
on training questions before the best one goes through Changes and the usual
check. A search attempt is on the new stage `searching`, keeps its settings and
progress in `improvement_iterations.search`, and may stop with `no_variant`
when nothing beat the instructions it started from. Skill sessions share the
stop reasons, so their constraint takes the value too.

`improvement_search_variants` holds each variant the search tried: its text,
the generation and parent it came from, and its score on training questions.
It belongs to its attempt's organization through a composite key, for which
`improvement_iterations` gains a unique `(id, organization_id)`.

The downgrade drops the variants and the column, reads a `searching` session as
`proposing` - the step a search hands its winner to - and `no_variant` as
`no_proposal`.

Revision ID: 0356_improvement_search
Revises: 0353_skill_check_verdict_version
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0356_improvement_search"
down_revision: str = "0353_skill_check_verdict_version"
branch_labels: None = None
depends_on: None = None

_STAGES_BEFORE = (
    "'analyzing', 'classifying', 'drafting', 'proposing', 'filtering', 'evaluating', 'judging'"
)
_STAGES = f"{_STAGES_BEFORE}, 'searching'"
_STOP_REASONS_BEFORE = (
    "'no_data', 'no_proposal', 'budget', 'inconclusive', 'regression', 'no_change', "
    "'max_iterations', 'repeat_candidate', 'permission', 'stale', 'stalled', 'proposal', "
    "'eval', 'superseded', 'knowledge_only', 'draft', 'expired', 'criteria_worse'"
)
_STOP_REASONS = f"{_STOP_REASONS_BEFORE}, 'no_variant'"


def _checks(stages: str, reasons: str) -> None:
    op.drop_constraint("ck_improvement_run_stage", "improvement_runs", type_="check")
    op.create_check_constraint(
        "ck_improvement_run_stage", "improvement_runs", f"stage IS NULL OR stage IN ({stages})"
    )
    op.drop_constraint("ck_improvement_run_stop_reason", "improvement_runs", type_="check")
    op.create_check_constraint(
        "ck_improvement_run_stop_reason",
        "improvement_runs",
        f"stop_reason IS NULL OR stop_reason IN ({reasons})",
    )
    op.drop_constraint(
        "ck_skill_improvement_run_stop_reason", "skill_improvement_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_skill_improvement_run_stop_reason",
        "skill_improvement_runs",
        f"stop_reason IS NULL OR stop_reason IN ({reasons})",
    )


def upgrade() -> None:
    _checks(_STAGES, _STOP_REASONS)
    op.add_column(
        "improvement_runs",
        sa.Column("mode", sa.String(length=16), server_default="steps", nullable=False),
    )
    op.create_check_constraint(
        "ck_improvement_run_mode", "improvement_runs", "mode IN ('steps', 'search')"
    )
    op.add_column(
        "improvement_iterations",
        sa.Column("search", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_unique_constraint(
        "uq_improvement_iterations_tenant", "improvement_iterations", ["id", "organization_id"]
    )
    op.create_table(
        "improvement_search_variants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("iteration_id", sa.UUID(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("rationale", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("train_score", sa.Numeric(precision=6, scale=5), nullable=True),
        sa.Column("cases_scored", sa.Integer(), nullable=False),
        sa.Column("cases_passed", sa.Integer(), nullable=False),
        sa.Column(
            "failures",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimate_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'scored', 'failed')",
            name=op.f("improvement_search_variants_ck_search_variant_status_check"),
        ),
        sa.CheckConstraint(
            "train_score IS NULL OR train_score BETWEEN 0 AND 1",
            name=op.f("improvement_search_variants_ck_search_variant_score_check"),
        ),
        sa.CheckConstraint(
            "generation >= 0 AND cases_scored >= 0 AND cases_passed BETWEEN 0 AND cases_scored "
            "AND attempts >= 0 AND estimate_usd >= 0 AND cost_usd >= 0",
            name=op.f("improvement_search_variants_ck_search_variant_counts_check"),
        ),
        sa.ForeignKeyConstraint(
            ["iteration_id", "organization_id"],
            ["improvement_iterations.id", "improvement_iterations.organization_id"],
            name=op.f("improvement_search_variants_iteration_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("improvement_search_variants_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["improvement_search_variants.id"],
            name=op.f("improvement_search_variants_parent_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("improvement_search_variants_pkey")),
        sa.UniqueConstraint("iteration_id", "text_hash", name="uq_improvement_search_variant_text"),
    )
    op.create_index(
        op.f("improvement_search_variants_organization_id_idx"),
        "improvement_search_variants",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_improvement_search_variants_rank",
        "improvement_search_variants",
        ["iteration_id", "status", "train_score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_improvement_search_variants_rank", table_name="improvement_search_variants")
    op.drop_index(
        op.f("improvement_search_variants_organization_id_idx"),
        table_name="improvement_search_variants",
    )
    op.drop_table("improvement_search_variants")
    op.drop_constraint("uq_improvement_iterations_tenant", "improvement_iterations", type_="unique")
    op.drop_column("improvement_iterations", "search")
    op.drop_constraint("ck_improvement_run_mode", "improvement_runs", type_="check")
    op.drop_column("improvement_runs", "mode")
    op.execute("UPDATE improvement_runs SET stage = 'proposing' WHERE stage = 'searching'")
    op.execute(
        "UPDATE improvement_runs SET stop_reason = 'no_proposal' WHERE stop_reason = 'no_variant'"
    )
    op.execute(
        "UPDATE skill_improvement_runs SET stop_reason = 'no_proposal' "
        "WHERE stop_reason = 'no_variant'"
    )
    _checks(_STAGES_BEFORE, _STOP_REASONS_BEFORE)
