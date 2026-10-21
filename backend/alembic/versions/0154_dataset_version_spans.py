"""Dataset versions: keep which versions hold a case revision on the revision itself.

`dataset_version_cases` gave every version a row per case it held, so a dataset
grew by every case on every change. A revision is only ever appended, or put in
the place of the revision it edits, and leaves at most once, so it is held by one
unbroken run of versions at one position. `dataset_cases` now records that run -
`added_in`, the first version holding the revision, and `removed_in`, the first
that no longer does - with the `position`, and the table goes. Version N holds
the revisions with `added_in <= N` and no `removed_in`, or one past N.

The upgrade derives the three columns from the membership rows and stops, naming
the dataset and the revision, on data no version of the code writes: a revision
held by no version, by versions that are not consecutive, at two positions, or
by another dataset's version. Nothing is guessed, because a version that read
differently afterwards would quietly change what an eval run compared.

The downgrade rebuilds the membership rows from the three columns, one row per
version a revision is held by, and drops them. It first refuses when an
organization's history needs more rows than the code it returns to allows -
`DATASET_MAX_VERSION_ROWS_PER_ORG`, read from the environment as that code reads
it - since history that stores only its changes can describe far more versions
than the old table could hold, and writing them all could fill the disk.

Revision ID: 0154_dataset_version_spans
Revises: 0151_eval_suites
Create Date: 2026-10-21
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0154_dataset_version_spans"
down_revision: str | None = "0151_eval_suites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SPANS = """
CREATE TEMPORARY TABLE dataset_case_spans AS
SELECT c.id,
       c.dataset_id,
       min(v.number) AS first,
       max(v.number) AS last,
       count(v.id) AS held,
       min(vc.position) AS position,
       max(vc.position) AS last_position,
       bool_or(v.dataset_id <> c.dataset_id) AS foreign_version
FROM dataset_cases c
LEFT JOIN dataset_version_cases vc ON vc.case_revision_id = c.id
LEFT JOIN dataset_versions v ON v.id = vc.version_id
GROUP BY c.id, c.dataset_id
"""

# Each check names the first offending revision, so the message says where to
# look and what would fix it; the operator fixes the data and runs the upgrade
# again, which starts over.
_REFUSE = """
DO $$
DECLARE
    bad record;
    others bigint;
BEGIN
    SELECT * INTO bad FROM dataset_case_spans WHERE held = 0 LIMIT 1;
    IF FOUND THEN
        SELECT count(*) - 1 INTO others FROM dataset_case_spans WHERE held = 0;
        RAISE EXCEPTION
            'Case revision % of dataset % is held by no version (and % more like it)',
            bad.id, bad.dataset_id, others
            USING HINT = 'Nothing reads such a revision. Delete it from dataset_cases '
                'and run the upgrade again.';
    END IF;

    SELECT * INTO bad FROM dataset_case_spans WHERE foreign_version LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'Case revision % of dataset % is held by another dataset''s version',
            bad.id, bad.dataset_id
            USING HINT = 'Delete its dataset_version_cases rows for versions of other '
                'datasets and run the upgrade again.';
    END IF;

    SELECT * INTO bad FROM dataset_case_spans WHERE held <> last - first + 1 LIMIT 1;
    IF FOUND THEN
        SELECT count(*) - 1 INTO others FROM dataset_case_spans WHERE held <> last - first + 1;
        RAISE EXCEPTION
            'Case revision % of dataset % is held by versions % to % with gaps '
            '(and % more like it)',
            bad.id, bad.dataset_id, bad.first, bad.last, others
            USING HINT = 'Add it to the versions between, or copy it into a new revision '
                'for the later ones, and run the upgrade again.';
    END IF;

    SELECT * INTO bad FROM dataset_case_spans WHERE position <> last_position LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'Case revision % of dataset % sits at positions % to % in its versions',
            bad.id, bad.dataset_id, bad.position, bad.last_position
            USING HINT = 'Give it one position in every version that holds it and run the '
                'upgrade again.';
    END IF;
END $$
"""

_BACKFILL = """
UPDATE dataset_cases c
SET position = s.position,
    added_in = s.first,
    removed_in = CASE WHEN s.last = d.latest_version THEN NULL ELSE s.last + 1 END
FROM dataset_case_spans s
JOIN datasets d ON d.id = s.dataset_id
WHERE c.id = s.id
"""

_LARGEST_HISTORY = """
SELECT organization_id, sum(case_count) AS rows
FROM dataset_versions
GROUP BY organization_id
ORDER BY rows DESC
LIMIT 1
"""

_REBUILD = """
INSERT INTO dataset_version_cases (version_id, case_revision_id, position)
SELECT v.id, c.id, c.position
FROM dataset_cases c
JOIN dataset_versions v
  ON v.dataset_id = c.dataset_id
 AND v.number >= c.added_in
 AND (c.removed_in IS NULL OR v.number < c.removed_in)
"""


def upgrade() -> None:
    op.add_column("dataset_cases", sa.Column("position", sa.Integer(), nullable=True))
    op.add_column("dataset_cases", sa.Column("added_in", sa.Integer(), nullable=True))
    op.add_column("dataset_cases", sa.Column("removed_in", sa.Integer(), nullable=True))
    op.execute(_SPANS)
    op.execute(_REFUSE)
    op.execute(_BACKFILL)
    op.execute("DROP TABLE dataset_case_spans")
    op.alter_column("dataset_cases", "position", nullable=False)
    op.alter_column("dataset_cases", "added_in", nullable=False)
    op.create_check_constraint(
        op.f("dataset_cases_ck_dataset_case_held_check"),
        "dataset_cases",
        "added_in >= 1 AND (removed_in IS NULL OR removed_in > added_in)",
    )
    op.create_index("ix_dataset_cases_held", "dataset_cases", ["dataset_id", "added_in"])
    op.create_index(
        "ix_dataset_cases_current",
        "dataset_cases",
        ["dataset_id", "position"],
        postgresql_where=sa.text("removed_in IS NULL"),
    )

    op.drop_index("ix_dataset_version_cases_order", table_name="dataset_version_cases")
    op.drop_index(
        op.f("dataset_version_cases_case_revision_id_idx"), table_name="dataset_version_cases"
    )
    op.drop_table("dataset_version_cases")


def _refuse_an_unholdable_history() -> None:
    ceiling = int(os.environ.get("DATASET_MAX_VERSION_ROWS_PER_ORG", "5000000"))
    largest = op.get_bind().execute(sa.text(_LARGEST_HISTORY)).first()
    if largest is not None and largest.rows > ceiling:
        raise RuntimeError(
            f"Organization {largest.organization_id}'s dataset versions hold "
            f"{largest.rows:,} cases between them, more than the "
            f"{ceiling:,} rows DATASET_MAX_VERSION_ROWS_PER_ORG lets the earlier schema "
            "store per organization. Delete datasets that organization no longer needs, "
            "or set DATASET_MAX_VERSION_ROWS_PER_ORG higher for this downgrade if the "
            "database has room for that many rows, and downgrade again."
        )


def downgrade() -> None:
    _refuse_an_unholdable_history()
    op.create_table(
        "dataset_version_cases",
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("case_revision_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_revision_id"],
            ["dataset_cases.id"],
            name=op.f("dataset_version_cases_case_revision_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name=op.f("dataset_version_cases_version_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "version_id", "case_revision_id", name=op.f("dataset_version_cases_pkey")
        ),
    )
    op.create_index(
        op.f("dataset_version_cases_case_revision_id_idx"),
        "dataset_version_cases",
        ["case_revision_id"],
        unique=False,
    )
    op.create_index(
        "ix_dataset_version_cases_order",
        "dataset_version_cases",
        ["version_id", "position"],
        unique=False,
    )
    op.execute(_REBUILD)

    op.drop_index("ix_dataset_cases_current", table_name="dataset_cases")
    op.drop_index("ix_dataset_cases_held", table_name="dataset_cases")
    op.drop_constraint(
        op.f("dataset_cases_ck_dataset_case_held_check"), "dataset_cases", type_="check"
    )
    op.drop_column("dataset_cases", "removed_in")
    op.drop_column("dataset_cases", "added_in")
    op.drop_column("dataset_cases", "position")
