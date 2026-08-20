"""A tracking row says which file it tracks.

`rag_documents` held a `filename` and nothing else identifying, so a row could
only be found again by name - and two objects with the same basename in one
bucket, `a/readme.md` beside `b/readme.md`, are indistinguishable that way. That
is the collision `0042`'s successor removed on the *vector* side (#990), reached
from the other direction: retiring "the previous row for this file" by name would
delete the other file's row.

So the address the ingest used is stored: `gdrive://<id>`, `s3://bucket/key`, or
an absolute path for a local or CLI sync. An upload stores none - its only name
is a basename, and two people can upload different files sharing one. With it, a
file that failed to parse on one sync and succeeded on the next stops leaving
both rows behind (#996).

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
    # `Text`, not `String(n)`: an S3 key alone reaches 1024 bytes before the
    # scheme and the bucket are added, and a filesystem path reaches 4096, so any
    # length picked here is a truncation error on a file that used to ingest fine.
    op.add_column("rag_documents", sa.Column("source_path", sa.Text(), nullable=True))
    # A hash index for the same reason. Equality is the only way this column is
    # ever read - `discard_failed` and nothing else - and a btree refuses a key
    # over about 2700 bytes at insert time, which would reintroduce the error the
    # `Text` avoids.
    op.create_index(
        "rag_documents_source_path_idx",
        "rag_documents",
        ["source_path"],
        unique=False,
        postgresql_using="hash",
    )


def downgrade() -> None:
    op.drop_index("rag_documents_source_path_idx", table_name="rag_documents")
    op.drop_column("rag_documents", "source_path")
