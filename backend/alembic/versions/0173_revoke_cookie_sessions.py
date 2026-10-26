"""End login sessions issued before the console cookie namespace changed.

The console deliberately ignores generic cookies, which can belong to another
application on the same hostname. Reauthentication cannot identify the abandoned
AgenticOS session without reading those cookies. Revoke existing sessions once
on upgrade instead, including rotated refresh chains and impersonations. API
keys are unaffected. Users and session-based API clients must sign in again.

Downgrade never reactivates credentials: a revoked session cannot safely be
restored, and signing in creates a fresh session on either application version.

Revision ID: 0173_revoke_cookie_sessions
Revises: 0172_mcp_health_queue_clock
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0173_revoke_cookie_sessions"
down_revision: str | None = "0172_mcp_health_queue_clock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE sessions SET is_active = false WHERE is_active IS true"))


def downgrade() -> None:
    """Revocation is irreversible; signing in recovers access."""
