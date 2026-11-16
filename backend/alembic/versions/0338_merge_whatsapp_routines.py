"""Merge the WhatsApp chain with the routine activation index.

Revision ID: 0338_merge_whatsapp_routines
Revises: 0337_whatsapp_customer_phone, 0332_routine_activation_lookup
"""

revision: str = "0338_merge_whatsapp_routines"
down_revision: tuple[str, str] = (
    "0337_whatsapp_customer_phone",
    "0332_routine_activation_lookup",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
