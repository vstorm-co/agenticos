"""Add the review and proposal half of browser teaching (#113, slice 2).

Revision ID: 0340_browser_teaching_review
Revises: 0339_browser_teaching_capture

A session in review gains reviewed step labels and parameter names (`review`),
the skill name the reviewer chose, and the source hash of the reviewed content
it asked to propose. `proposing` is the state while the one proposal job is
queued; `proposed` is terminal and links the proposal. A proposed session keeps
no steps or review: the proposal holds the reviewed procedure from then on.

`skill_proposals.browser_teaching_id` is the typed provenance of a proposal made
from a demonstration. It is unique, so one session can never produce a second
proposal, whatever the queue does.

Both tables are additive. The sessions table holds only transient rows behind a
disabled flag, so the new columns take defaults and no backfill is needed.
Downgrade erases sessions in the new states before restoring the old checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0340_browser_teaching_review"
down_revision: str | None = "0339_browser_teaching_capture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "browser_teaching_sessions"
_STATES_BEFORE = "'recording', 'paused', 'review', 'discarded', 'expired'"
_ERASED_BEFORE = (
    "status NOT IN ('discarded', 'expired') OR "
    "(sanitized_events = '[]'::jsonb AND allowed_origins = '[]'::jsonb AND title = '')"
)


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "review",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(_TABLE, sa.Column("proposal_name", sa.String(length=64), nullable=True))
    op.add_column(_TABLE, sa.Column("source_hash", sa.String(length=64), nullable=True))
    op.drop_constraint(op.f("browser_teaching_sessions_state_check"), _TABLE, type_="check")
    op.create_check_constraint(
        op.f("browser_teaching_sessions_state_check"),
        _TABLE,
        f"status IN ({_STATES_BEFORE}, 'proposing', 'proposed')",
    )
    op.drop_constraint(op.f("browser_teaching_sessions_erased_check"), _TABLE, type_="check")
    op.create_check_constraint(
        op.f("browser_teaching_sessions_erased_check"),
        _TABLE,
        "status NOT IN ('discarded', 'expired') OR "
        "(sanitized_events = '[]'::jsonb AND allowed_origins = '[]'::jsonb AND title = '' "
        "AND review = '[]'::jsonb AND proposal_name IS NULL AND source_hash IS NULL)",
    )
    op.create_check_constraint(
        op.f("browser_teaching_sessions_review_check"),
        _TABLE,
        "jsonb_typeof(review) = 'array' AND jsonb_array_length(review) <= 500 "
        "AND octet_length(review::text) <= 131072",
    )
    op.create_check_constraint(
        op.f("browser_teaching_sessions_proposed_check"),
        _TABLE,
        "status <> 'proposed' OR (sanitized_events = '[]'::jsonb AND review = '[]'::jsonb)",
    )
    op.create_check_constraint(
        op.f("browser_teaching_sessions_proposing_check"),
        _TABLE,
        "status NOT IN ('proposing', 'proposed') OR (source_hash IS NOT NULL AND proposal_name IS NOT NULL)",
    )

    op.add_column(
        "skill_proposals",
        sa.Column("browser_teaching_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("skill_proposals_browser_teaching_id_fkey"),
        "skill_proposals",
        _TABLE,
        ["browser_teaching_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("skill_proposals_browser_teaching_id_idx"),
        "skill_proposals",
        ["browser_teaching_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("skill_proposals_browser_teaching_id_idx"), table_name="skill_proposals")
    op.drop_constraint(
        op.f("skill_proposals_browser_teaching_id_fkey"), "skill_proposals", type_="foreignkey"
    )
    op.drop_column("skill_proposals", "browser_teaching_id")

    op.execute(
        f"UPDATE {_TABLE} SET status = 'discarded', sanitized_events = '[]'::jsonb, "
        "allowed_origins = '[]'::jsonb, title = '', hold_id = NULL, review = '[]'::jsonb, "
        "proposal_name = NULL, source_hash = NULL "
        "WHERE status IN ('proposing', 'proposed')"
    )
    op.drop_constraint(op.f("browser_teaching_sessions_proposing_check"), _TABLE, type_="check")
    op.drop_constraint(op.f("browser_teaching_sessions_proposed_check"), _TABLE, type_="check")
    op.drop_constraint(op.f("browser_teaching_sessions_review_check"), _TABLE, type_="check")
    op.drop_constraint(op.f("browser_teaching_sessions_erased_check"), _TABLE, type_="check")
    op.create_check_constraint(
        op.f("browser_teaching_sessions_erased_check"), _TABLE, _ERASED_BEFORE
    )
    op.drop_constraint(op.f("browser_teaching_sessions_state_check"), _TABLE, type_="check")
    op.create_check_constraint(
        op.f("browser_teaching_sessions_state_check"), _TABLE, f"status IN ({_STATES_BEFORE})"
    )
    op.drop_column(_TABLE, "source_hash")
    op.drop_column(_TABLE, "proposal_name")
    op.drop_column(_TABLE, "review")
