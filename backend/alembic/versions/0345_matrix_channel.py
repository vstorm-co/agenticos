"""A Matrix bot can be an agent's exposure surface (#2081).

Revision ID: 0345_matrix_channel
Revises: 0344_user_appearance
Create Date: 2026-11-19

Native Matrix identifiers exceed the old chat and identity limits. Opaque private
conversation keys also retain their recipient across durable delivery. Widen
without changing stored keys; rollback refuses data that no longer fits rather
than truncating identifiers or silently discarding conversation history.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0345_matrix_channel"
down_revision: str | None = "0344_user_appearance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SURFACE_CHECK = "agent_exposures_ck_exposure_surface_check"
_SURFACES = "'slack', 'telegram', 'mattermost', 'teams', 'discord', 'sms', 'email', 'imessage'"


_IDENTIFIER_LIMITS: tuple[tuple[str, str, int, int | None], ...] = (
    ("channel_sessions", "platform_chat_id", 100, None),
    ("channel_observations", "platform_chat_id", 512, None),
    ("channel_identities", "platform_user_id", 100, 255),
    ("channel_identities", "platform_username", 100, 255),
    ("channel_link_requests", "platform_user_id", 100, 255),
    ("channel_link_requests", "platform_username", 100, 255),
)


_SCOPED_ACCOUNTS: tuple[tuple[str, str], ...] = (
    ("channel_identities", "uq_channel_identity_platform_user"),
    ("channel_link_requests", "channel_link_requests_identity_key"),
)


def upgrade() -> None:
    for table, constraint in _SCOPED_ACCOUNTS:
        op.add_column(
            table, sa.Column("server_url", sa.String(500), nullable=False, server_default="")
        )
        op.drop_constraint(op.f(constraint), table, type_="unique")
        op.create_unique_constraint(
            op.f(constraint), table, ["platform", "platform_user_id", "server_url"]
        )
    for table, column, previous, current in _IDENTIFIER_LIMITS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(previous),
            type_=sa.Text() if current is None else sa.String(current),
        )
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        f"surface IN ({_SURFACES}, 'matrix')",
    )


def downgrade() -> None:
    oversized = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} WHERE char_length({column}) > {previous})"
        for table, column, previous, _ in _IDENTIFIER_LIMITS
    )
    scoped = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} WHERE server_url <> '')" for table, _ in _SCOPED_ACCOUNTS
    )
    op.execute(
        "DO $$ BEGIN IF " + oversized + " OR " + scoped + " THEN RAISE EXCEPTION "
        "'Cannot downgrade Matrix identifiers: remove or migrate homeserver-bound accounts "
        "and identifiers exceeding legacy limits first; conversation history is preserved'; "
        "END IF; END $$"
    )
    op.execute("DELETE FROM agent_exposures WHERE surface = 'matrix'")
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        f"surface IN ({_SURFACES})",
    )
    for table, column, previous, current in reversed(_IDENTIFIER_LIMITS):
        op.alter_column(
            table,
            column,
            existing_type=sa.Text() if current is None else sa.String(current),
            type_=sa.String(previous),
        )
    for table, constraint in reversed(_SCOPED_ACCOUNTS):
        op.drop_constraint(op.f(constraint), table, type_="unique")
        op.create_unique_constraint(op.f(constraint), table, ["platform", "platform_user_id"])
        op.drop_column(table, "server_url")
