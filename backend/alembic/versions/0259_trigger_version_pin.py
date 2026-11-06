"""Let a routine pin an immutable version rather than follow an environment.

Null preserves every existing routine's resolution. A version pin and an
environment are exclusive, and deleting a pinned version is refused rather than
silently running a newer version with different instructions or capabilities.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0259_trigger_version_pin"
down_revision: str | None = "0258_primary_channel_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_triggers", sa.Column("pinned_version_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "agent_triggers_pinned_version_id_fkey",
        "agent_triggers",
        "agent_versions",
        ["pinned_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_trigger_version_target",
        "agent_triggers",
        "pinned_version_id IS NULL OR environment_id IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trigger_version_target", "agent_triggers", type_="check")
    op.drop_constraint(
        "agent_triggers_pinned_version_id_fkey", "agent_triggers", type_="foreignkey"
    )
    op.drop_column("agent_triggers", "pinned_version_id")
