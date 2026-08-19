"""Whether a publish moves an environment on its own.

Publish repointed the default environment silently, so "publish" and "deploy to
production" were the same click and nothing on screen said so. Each environment
now says which it is: pinned - the default - waits to be promoted onto, and
`tracks_latest` follows every publish, which is what a `dev` an author is
iterating in wants.

**Existing environments become pinned**, including the defaults that were being
repointed. That is the behaviour change this exists for: an agent published
after this migration mints a version and leaves every environment where it was
until somebody promotes. An author who wants the old behaviour switches the
environment back to `tracks_latest`, which is now a visible choice rather than a
rule nobody could see.

Revision ID: 0040_environment_release_mode
Revises: 0039_deployment_limits
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040_environment_release_mode"
down_revision: str | None = "0039_deployment_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_environments",
        sa.Column("tracks_latest", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("agent_environments", "tracks_latest")
