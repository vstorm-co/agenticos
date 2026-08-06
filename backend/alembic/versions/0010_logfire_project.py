"""Which Logfire project a trace went to

Revision ID: 0010_logfire_project
Revises: 0009_align_index_names
Create Date: 2026-08-07

`agent_runs.logfire_trace_id` has existed since the baseline and has never been
written. Filling it is only half a deep link: a Logfire URL needs the project as
well, and a *write* token - which is all the platform ever holds - carries no
project name. So the slug has to be configured, and it has to be configured
wherever the token is, or a link points into a project the trace never reached.

Two columns for two levels of that:

`agent_environments.logfire_project` sits beside the token that column already
holds. An environment redirecting its runs to a client's project supplies both
halves or neither; it never borrows the spec's slug, because that would pair one
project's traces with another project's URL. (The third level, an agent's own
spec, is a spec field rather than a column - `ObservabilitySpec.project`, spec
version 8.)

`agent_runs.logfire_project` records where the trace actually went, the way
`provider` and `model_label` record what actually ran. Resolving it at read time
instead would relabel every historical run the day somebody repoints an agent -
links into a project those traces are not in.

Both nullable, no backfill and no default. Every existing run has a null trace id
and therefore no project to name; inventing the deployment's current slug for
them would claim traces exist that were never exported.
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_logfire_project"
down_revision = "0009_align_index_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_environments", sa.Column("logfire_project", sa.String(length=128), nullable=True)
    )
    op.add_column("agent_runs", sa.Column("logfire_project", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "logfire_project")
    op.drop_column("agent_environments", "logfire_project")
