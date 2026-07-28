"""Mattermost as a channel: a per-bot server URL, and a third exposure surface

Revision ID: 0048_mattermost
Revises: 0047_drop_is_demo
Create Date: 2026-07-28

Two changes, both forced by the same fact: Mattermost is self-hosted.

`channel_bots.api_base_url` — Slack and Telegram each have one address for
every customer, so the adapter can hard-code it. A Mattermost bot belongs to
somebody's own server and cannot post anywhere without being told which one.
Nullable because the other two platforms have nothing to put there.

`ck_exposure_surface` gains `mattermost`. The constraint is the reason an agent
cannot be exposed on a surface the platform does not have an adapter for, which
is worth keeping — so it has to be widened deliberately, here, rather than
discovered when an insert fails.
"""

import sqlalchemy as sa

from alembic import op

revision = "0048_mattermost"
down_revision = "0047_drop_is_demo"
branch_labels = None
depends_on = None

_OLD = "surface IN ('slack', 'telegram')"
_NEW = "surface IN ('slack', 'telegram', 'mattermost')"


def upgrade() -> None:
    op.add_column("channel_bots", sa.Column("api_base_url", sa.String(length=500), nullable=True))
    op.drop_constraint("ck_exposure_surface", "agent_exposures", type_="check")
    op.create_check_constraint("ck_exposure_surface", "agent_exposures", _NEW)


def downgrade() -> None:
    # Any Mattermost binding has to go first: the narrower constraint cannot be
    # created while a row violates it, and failing halfway through a downgrade
    # is worse than removing the rows the surface no longer supports.
    op.execute(sa.text("DELETE FROM agent_exposures WHERE surface = 'mattermost'"))
    op.drop_constraint("ck_exposure_surface", "agent_exposures", type_="check")
    op.create_check_constraint("ck_exposure_surface", "agent_exposures", _OLD)
    op.drop_column("channel_bots", "api_base_url")
