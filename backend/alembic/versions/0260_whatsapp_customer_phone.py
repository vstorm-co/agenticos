"""A WhatsApp customer's number, kept for the people who manage the line (#2076).

Revision ID: 0260_whatsapp_customer_phone
Revises: 0259_whatsapp_public_line
Create Date: 2026-11-04

`whatsapp_customers.phone` holds the digits of the number of a customer the line
answers with no linked account, so a manager can find them again and erase them.
It is nullable, has no index and no constraint, and is cleared when the customer
links an account. Existing rows have none.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0260_whatsapp_customer_phone"
down_revision: str | None = "0259_whatsapp_public_line"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("whatsapp_customers", sa.Column("phone", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("whatsapp_customers", "phone")
