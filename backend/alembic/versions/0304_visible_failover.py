"""Record which model served a run, so a fallback stops being invisible.

Until this change the run row named the primary profile however the turn was
answered: a fallback served the turn and the record still said the primary,
so a bad answer could not be traced to the model that gave it. Two columns
on `agent_runs` close that hole:

- `fallback_used` - true when any request of the run was served by a fallback
  model in the run's chain. Non-nullable with a server default of false, so
  rows written before this was tracked read as "not recorded" and need no
  backfill; the console only renders the fallback line when it is true.
- `serving_model` - the bare model id the provider reported for the last
  successful request of the run, or null when no request succeeded. Nullable:
  a run that never reached a model has nothing to name.

The values are derived from the per-request models in the run manifest, never
from `model_label`, which is a display name somebody chose rather than a model
id.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0304_visible_failover"
down_revision: str | None = "0303_artifact_favourites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "fallback_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("agent_runs", sa.Column("serving_model", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "serving_model")
    op.drop_column("agent_runs", "fallback_used")
