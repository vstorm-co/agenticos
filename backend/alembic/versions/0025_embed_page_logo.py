"""A hosted page may show a picture uploaded for it.

Its other two choices - the agent's avatar, the organization's - are images this
platform already stores, so `config.logo` only had to name which. An uploaded one
needs somewhere for the file to live, and the question is which side of the wall
it lives on.

A column, not a field in `config`. `config` is submitted by a client and the
stored path is read back and streamed by a *public* route, so a path accepted
from a request body would let a caller name any file this process can open.
`agent_embeds.logo_path` is written only by the upload route, which puts the
bytes there itself.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_embed_page_logo"
down_revision: str | Sequence[str] | None = "0024_run_channel_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_embeds", sa.Column("logo_path", sa.String(length=512), nullable=True))


def downgrade() -> None:
    # A row that named an uploaded file goes back to the agent's avatar, which is
    # the default and the only choice the old schema could express. The file
    # itself is left where it is: this reverses a schema, not an upload.
    op.execute(
        """
        UPDATE agent_embeds
           SET config = jsonb_set(config, '{logo}', '"agent"')
         WHERE config->>'logo' = 'custom'
        """
    )
    op.drop_column("agent_embeds", "logo_path")
