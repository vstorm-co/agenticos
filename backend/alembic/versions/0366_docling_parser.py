"""Docling as a document parser: its connection kind and the task a parse is waiting on.

Revision ID: 0366_docling_parser
Revises: 0365_service_connections
Create Date: 2026-11-26

`service_connections.kind` gains `document_parser`, and `rag_documents` gains
`parser_task`, the Docling Serve task a document's parse is waiting on.

The CHECK is replaced through raw SQL: the stored name is the naming convention
applied once (see 0365), and `drop_constraint` would apply it a second time. The
longest name the convention can make is 63 characters; this one is 54.
`document_parser` is 15 characters and fits `kind VARCHAR(16)`.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0366_docling_parser"
down_revision = "0365_service_connections"
branch_labels = None
depends_on = None

_KIND_CHECK = "service_connections_ck_service_connections_kind_check"


def upgrade() -> None:
    op.execute(f"ALTER TABLE service_connections DROP CONSTRAINT {_KIND_CHECK}")
    op.execute(
        f"ALTER TABLE service_connections ADD CONSTRAINT {_KIND_CHECK} "
        "CHECK (kind IN ('embedding', 'ocr', 'document_parser'))"
    )
    op.add_column("rag_documents", sa.Column("parser_task", JSONB, nullable=True))


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT count(*) FROM service_connections WHERE kind = 'document_parser'")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Cannot downgrade: {count} document_parser service connection(s) exist and the "
            "older constraint would reject them. Delete them first."
        )
    op.drop_column("rag_documents", "parser_task")
    op.execute(f"ALTER TABLE service_connections DROP CONSTRAINT {_KIND_CHECK}")
    op.execute(
        f"ALTER TABLE service_connections ADD CONSTRAINT {_KIND_CHECK} "
        "CHECK (kind IN ('embedding', 'ocr'))"
    )
