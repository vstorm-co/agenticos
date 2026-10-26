"""Join trigger integrations with the released execution hardening migrations.

Both branches descend from 0170_generated_media and change independent tables
or columns. Preserve their existing revision ids so databases that tested either
branch can upgrade without stamping or replaying an applied migration.

Revision ID: 0175_merge_trigger_integrations
Revises: 0174_file_calendar_sources, 0174_message_client_id
Create Date: 2026-10-26
"""

revision = "0175_merge_trigger_integrations"
down_revision = ("0174_file_calendar_sources", "0174_message_client_id")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
