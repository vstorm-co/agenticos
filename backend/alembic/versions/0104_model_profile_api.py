"""Record which of OpenAI's two APIs a model profile uses.

Every `openai` profile was built on Chat Completions, which is what the
OpenAI-compatible servers reached through `base_url` implement. OpenAI's newest
models are served on the Responses API only and answer Chat Completions with a
400, so a profile pointed at them failed at its first request. Deciding by
whether `base_url` is set was the alternative, and it is wrong both ways: a
regional OpenAI endpoint or a gateway in front of OpenAI has a `base_url` and
serves Responses, and a vLLM may serve either. So the profile stores the choice.

The backfill gives existing rows the default a new one gets: an `openai` profile
on OpenAI's own endpoint uses Responses, one with a `base_url` keeps Chat
Completions, and every `azure` profile keeps Chat Completions, which is what
both were built on until now. Every other provider serves one API and stays null.

Revision ID: 0104_model_profile_api
Revises: 0103_skill_library_fingerprint
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0104_model_profile_api"
down_revision: str | None = "0103_skill_library_fingerprint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_profiles", sa.Column("api", sa.String(16), nullable=True))
    op.execute(
        "UPDATE model_profiles SET api = CASE WHEN base_url IS NULL THEN 'responses' "
        "ELSE 'chat' END WHERE provider = 'openai'"
    )
    op.execute("UPDATE model_profiles SET api = 'chat' WHERE provider = 'azure'")


def downgrade() -> None:
    op.drop_column("model_profiles", "api")
