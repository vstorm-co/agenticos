"""Agents get a face

Revision ID: 0040_agent_avatar
Revises: 0039_exposures
Create Date: 2026-07-27

A nullable storage path on the agent row, mirroring users and organizations.

Not in the spec, and that is the decision worth recording. The spec is what the
agent *is* - it validates, freezes into a version, and exports to YAML for
somebody's git repository. Putting a picture in it would mean a new version
every time somebody changed the picture, and a diff in a reviewed artifact for
something that cannot change an answer.
"""

import sqlalchemy as sa

from alembic import op

revision = "0040_agent_avatar"
down_revision = "0039_exposures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("avatar_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "avatar_url")
