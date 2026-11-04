"""Record that a model profile runs with no key on purpose (#2478).

`model_profiles.secret_id` is `ON DELETE SET NULL`, so a profile whose vault key
was deleted and a self-hosted one saved with no key looked the same: a keyless
provider (OpenAI counts, because OpenAI-compatible servers exist) with an
endpoint. The first was treated as the second, stayed selectable and failed at
its gateway with an authentication error. The intent is now a column, written
when a profile is saved; a deleted key leaves it false, which reads as "no key".

The backfill keeps every profile that resolves today resolving: a row with no
key, an endpoint and a keyless provider is marked as running without a key.
Some of those may be profiles whose key was deleted before this revision; the
two cannot be told apart from the rows, and changing what an existing profile
does is not this migration's to decide.

Revision ID: 0175_profile_runs_without_key
Revises: 0174_message_client_id
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0175_profile_runs_without_key"
down_revision: str | None = "0174_message_client_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_profiles",
        sa.Column("runs_without_key", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE model_profiles SET runs_without_key = true "
        "WHERE secret_id IS NULL AND base_url IS NOT NULL "
        "AND provider IN ('openai', 'ollama', 'litellm')"
    )


def downgrade() -> None:
    op.drop_column("model_profiles", "runs_without_key")
