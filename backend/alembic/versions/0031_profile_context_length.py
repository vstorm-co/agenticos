"""How many tokens a model profile's model accepts.

Recorded on the profile because the request path has no way to ask. The
`compaction` capability triggers on a fraction of the context window, and the
only source it could resolve one from is the `genai-prices` snapshot — which is
wrong here in the direction that breaks a run rather than the one that wastes a
summary: it records 1,000,000 for `anthropic:claude-sonnet-4-5` against a real
200,000, and a profile with fallbacks builds a `FallbackModel` whose composite
`fallback:...` id resolves to nothing at all.

The provider's own listing already carries the number — it is what the model
picker shows — so it is read once, when the profile is created, and stored.

Nullable, and null means **not recorded** rather than zero: a profile created
before this column existed has none, so does a provider that publishes no
length, and so does one whose listing could not be reached. All three fall back
to resolving the window at run time, exactly as before.

The revision id is shortened from the obvious one: `alembic_version.version_num`
is `varchar(32)`, and `0031_model_profile_context_length` is 33.

Revision ID: 0031_profile_context_length
Revises: 0030_context_files
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031_profile_context_length"
down_revision: str | None = "0030_context_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_profiles",
        sa.Column("context_length", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_profiles", "context_length")
