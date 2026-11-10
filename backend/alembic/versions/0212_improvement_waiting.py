"""Improvement sessions that wait for a person between steps.

`improvement_runs.status` gains `waiting`, a session that finished a step and
waits for a person to take the next one, and `stop_reason` gains `expired`, a
session nobody took further for seven days. A session is open until it is
decided, discarded, cancelled or outdated, and an agent has at most one open
session: where one has several, all but the one most likely in use - a moving
session, else the newest - are marked stale as superseded before the index is
built.

`improvement_runs` gains who took the latest step and with which credential;
`improvement_iterations` gains the note a person left for an attempt's helper
and the attempt's own draw of learning and measured questions; and
`spec_proposal_hunks` gains a person's edit of a proposal before it is checked.

The downgrade stops every waiting session as superseded, reads an expired one
as stale, and drops what this revision added.

Revision ID: 0212_improvement_waiting
Revises: 0211_knowledge_draft_job
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0212_improvement_waiting"
down_revision: str | None = "0211_knowledge_draft_job"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every value the improvement models allow after this revision, as the CHECK
# constraints and partial indexes spell them.
_STATUSES_BEFORE = (
    "'queued', 'running', 'ready', 'stopped', 'failed', 'cancelled', 'stale', "
    "'accepted', 'published', 'rejected'"
)
_STATUSES = (
    "'queued', 'running', 'waiting', 'ready', 'stopped', 'failed', 'cancelled', 'stale', "
    "'accepted', 'published', 'rejected'"
)
_STAGES = (
    "'analyzing', 'classifying', 'drafting', 'proposing', 'filtering', 'evaluating', 'judging'"
)
_VERDICTS = "'better', 'no_change', 'regression', 'inconclusive'"
_ACTIVE = "'queued', 'running'"
_OPEN = "'queued', 'running', 'waiting', 'ready', 'stopped', 'failed'"
_UNSETTLED = "'queued', 'running', 'waiting', 'ready', 'stopped', 'failed', 'accepted'"
_OPEN_BEFORE = "'queued', 'running', 'ready', 'stopped', 'failed'"
_UNSETTLED_BEFORE = "'queued', 'running', 'ready', 'accepted'"
_STOP_REASONS_BEFORE = (
    "'no_data', 'no_proposal', 'budget', 'inconclusive', 'regression', 'no_change', "
    "'max_iterations', 'repeat_candidate', 'permission', 'stale', 'stalled', 'proposal', "
    "'eval', 'superseded', 'knowledge_only', 'draft'"
)
_STOP_REASONS = f"{_STOP_REASONS_BEFORE}, 'expired'"

_ITERATION_COLUMNS = ("note", "split_seed", "train_case_ids", "holdout_case_ids")


def _checks(statuses: str, reasons: str) -> None:
    op.drop_constraint("ck_improvement_run_status", "improvement_runs", type_="check")
    op.create_check_constraint(
        "ck_improvement_run_status", "improvement_runs", f"status IN ({statuses})"
    )
    op.drop_constraint("ck_improvement_run_stop_reason", "improvement_runs", type_="check")
    op.create_check_constraint(
        "ck_improvement_run_stop_reason",
        "improvement_runs",
        f"stop_reason IS NULL OR stop_reason IN ({reasons})",
    )


def _indexes(*, unique: tuple[str, str], listed: tuple[str, str]) -> None:
    op.create_index(
        unique[0],
        "improvement_runs",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({unique[1]})"),
    )
    op.create_index(
        listed[0],
        "improvement_runs",
        ["status"],
        postgresql_where=sa.text(f"status IN ({listed[1]})"),
    )


def upgrade() -> None:
    _checks(_STATUSES, _STOP_REASONS)
    op.execute(
        f"""
        UPDATE improvement_runs AS run
        SET status = 'stale', stop_reason = 'superseded',
            finished_at = coalesce(run.finished_at, now())
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY agent_id
                ORDER BY status IN ({_ACTIVE}) DESC, created_at DESC, id DESC
            ) AS place
            FROM improvement_runs
            WHERE status IN ({_OPEN_BEFORE})
        ) AS ranked
        WHERE run.id = ranked.id AND ranked.place > 1
        """
    )
    op.drop_index("ix_improvement_runs_open", table_name="improvement_runs")
    op.drop_index("uq_improvement_runs_active", table_name="improvement_runs")
    _indexes(
        unique=("uq_improvement_runs_open", _OPEN),
        listed=("ix_improvement_runs_unsettled", _UNSETTLED),
    )

    op.add_column(
        "improvement_runs",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("improvement_runs_actor_user_id_fkey"),
        "improvement_runs",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "improvement_runs",
        sa.Column("actor_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("improvement_iterations", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("improvement_iterations", sa.Column("split_seed", sa.Integer(), nullable=True))
    for column in ("train_case_ids", "holdout_case_ids"):
        op.add_column(
            "improvement_iterations",
            sa.Column(column, postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        )
    op.add_column("spec_proposal_hunks", sa.Column("edited_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("spec_proposal_hunks", "edited_text")
    for column in reversed(_ITERATION_COLUMNS):
        op.drop_column("improvement_iterations", column)
    op.drop_column("improvement_runs", "actor_api_key_id")
    op.drop_constraint(
        op.f("improvement_runs_actor_user_id_fkey"), "improvement_runs", type_="foreignkey"
    )
    op.drop_column("improvement_runs", "actor_user_id")

    op.drop_index("ix_improvement_runs_unsettled", table_name="improvement_runs")
    op.drop_index("uq_improvement_runs_open", table_name="improvement_runs")
    op.execute(
        "UPDATE improvement_runs SET status = 'stopped', stop_reason = 'superseded', "
        "finished_at = coalesce(finished_at, now()) WHERE status = 'waiting'"
    )
    op.execute("UPDATE improvement_runs SET stop_reason = 'stale' WHERE stop_reason = 'expired'")
    _checks(_STATUSES_BEFORE, _STOP_REASONS_BEFORE)
    _indexes(
        unique=("uq_improvement_runs_active", _ACTIVE),
        listed=("ix_improvement_runs_open", _UNSETTLED_BEFORE),
    )
