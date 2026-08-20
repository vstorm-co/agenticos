"""A tracking row says which file it tracks.

`rag_documents` held a `filename` and nothing else identifying, so a row could
only be found again by name - and two objects with the same basename in one
bucket, `a/readme.md` beside `b/readme.md`, are indistinguishable that way. That
is the collision `0042`'s successor removed on the *vector* side (#990), reached
from the other direction: retiring "the previous row for this file" by name would
delete the other file's row.

So the address the ingest used is stored: `gdrive://<id>`, `s3://bucket/key`, an
absolute path for a local-directory sync, and the filename itself for an upload,
which has no address of its own. With it, a file that failed to parse on one sync
and succeeded on the next stops leaving both rows behind (#996).

**Nullable, and nothing is backfilled.** A row written before this column is a
row whose address nobody recorded, and inventing one from its filename is exactly
the guess this column exists to avoid: it would claim `readme.md` is the same
file as some other `readme.md`. Those rows keep `NULL` and are simply never
matched by address, which is the truthful answer - they are still matched by the
vector document they point at, which is how a replacement has always retired one.

Revision ID: 0043_rag_document_source_path
Revises: 0042_sync_source_secret_id
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043_rag_document_source_path"
down_revision: str | None = "0042_sync_source_secret_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rag_documents", sa.Column("source_path", sa.String(length=1024), nullable=True))
    op.create_index("rag_documents_source_path_idx", "rag_documents", ["source_path"], unique=False)


def downgrade() -> None:
    op.drop_index("rag_documents_source_path_idx", table_name="rag_documents")
    op.drop_column("rag_documents", "source_path")
