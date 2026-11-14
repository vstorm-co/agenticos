"""A guard suite's pinned dataset version and scoring (#2363).

A suite that guards an environment read the latest version of its dataset and
the dataset's scoring as they stood, so anybody who could edit the dataset
moved what the guard checked. A guard now holds the version and the scoring it
was set up with. The suites already guarding an environment are pinned to what
their dataset holds now - the same thing they would have read on their next
run - except one whose dataset has no version yet, which stays unpinned until
it has one.

Revision ID: 0182_eval_suite_pin
Revises: 0178_eval_run_proposal_check
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0182_eval_suite_pin"
down_revision: str | None = "0178_eval_run_proposal_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "eval_suites_ck_eval_suite_pin_check"


def upgrade() -> None:
    op.add_column("eval_suites", sa.Column("pinned_dataset_version", sa.Integer(), nullable=True))
    op.add_column(
        "eval_suites",
        sa.Column("pinned_scoring", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        """
        UPDATE eval_suites AS suite
        SET pinned_dataset_version = dataset.latest_version,
            pinned_scoring = dataset.scoring
        FROM datasets AS dataset
        WHERE dataset.id = suite.dataset_id
          AND dataset.latest_version > 0
          AND EXISTS (
              SELECT 1 FROM agent_environment_guards AS guard WHERE guard.suite_id = suite.id
          )
        """
    )
    op.create_check_constraint(
        op.f(_CHECK),
        "eval_suites",
        "(pinned_dataset_version IS NULL) = (pinned_scoring IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "eval_suites", type_="check")
    op.drop_column("eval_suites", "pinned_scoring")
    op.drop_column("eval_suites", "pinned_dataset_version")
