"""Record which bundled version a skill was copied from, so `seed-skills` can refresh it.

`seed-skills` left every skill an organization already had exactly as it was, so
an improved bundled skill never reached an organization seeded with the previous
one. `library_fingerprint` is the hash of the folder a row was last written from:
a row that still matches it is unedited and may be replaced by a newer version, a
row that does not was edited here and is left alone. Existing rows keep null,
which `seed-skills` reports as untracked rather than guessing whether they were
edited.

Revision ID: 0103_skill_library_fingerprint
Revises: 0102_session_rotated_at
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0103_skill_library_fingerprint"
down_revision: str | None = "0102_session_rotated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("library_fingerprint", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("skills", "library_fingerprint")
