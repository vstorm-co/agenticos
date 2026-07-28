"""Which version of the agent said it

Revision ID: 0044_message_version
Revises: 0043_org_monthly_budget
Create Date: 2026-07-27

0041 recorded which agent answered. That is not enough to read an old
conversation: an agent is rewritten, and the words in a transcript were produced
by one frozen spec, not by whatever the agent has since become. Runs have
recorded ``agent_version_id`` since they existed; messages had only the agent,
so a transcript could name the speaker and never the thing that spoke.

``SET NULL`` for the same reason as the agent column: deleting an agent takes
its versions with it, and that must not take the conversation. The answer stays,
its provenance does not — which is the truth, and better than a hole in
somebody's history.

Nothing is backfilled. A run row could supply it for the conversations that have
one, but a run is per turn and a message is not always the turn it belongs to;
matching them after the fact would be a guess written into a column whose whole
value is that it is not one.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0044_message_version"
down_revision = "0043_org_monthly_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("agent_version_id", PG_UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "messages_agent_version_id_fkey",
        "messages",
        "agent_versions",
        ["agent_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("messages_agent_version_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "agent_version_id")
