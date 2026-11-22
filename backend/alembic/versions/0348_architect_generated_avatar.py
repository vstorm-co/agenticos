"""Use ordinary generated avatars for the installed Architect.

Only the recorded shipped picture is cleared. Uploaded replacements and already
cleared pictures retain their owner's choice. Files are not deleted. The old
mark path remains as provenance; downgrade does not restore pictures because a
later explicit clear must not be mistaken for this backfill.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0348_architect_generated_avatar"
down_revision: str = "0347_console_experience"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE agents AS agent SET avatar_url = NULL "
            "FROM organization_assistants AS assistant "
            "WHERE agent.id = assistant.agent_id "
            "AND agent.organization_id = assistant.organization_id "
            "AND assistant.mark_path IS NOT NULL "
            "AND agent.avatar_url = assistant.mark_path"
        )
    )


def downgrade() -> None:
    pass
