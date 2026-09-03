"""Agent memory facts carry an `origin`, like files (#788).

Facts began without an `origin`: the design held that every fact was
agent-authored and none was ever injected into instructions, so the file store's
trust tier did not apply. Both halves stopped being true on this branch. An
operator can now seed a fact through the management API (`create_fact`), and the
standing memory brief injects remembered facts into the agent's instructions.
Injecting an agent-authored fact is exactly the untrusted-input-as-prompt the
file `origin` exists to prevent - and, narrowly, an agent-written *shared* fact
would reach every end-user's instructions. So a fact gets the same `origin`
column and CHECK a file has, and the brief injects only the trusted-injectable
set (a person's own facts, and operator-authored shared ones), never an
agent-authored shared fact.

Existing rows predate the column and cannot be attributed reliably, so they
backfill to `agent` - the conservative tier: an unattributable fact is treated as
untrusted and kept out of the shared brief, reachable only through `recall`. The
column is added with that as a server default to fill those rows, then the
default is dropped, so the application sets `origin` on every write (`agent` from
the runtime `remember`, `operator` from `create_fact`), matching the model, which
mirrors `agent_memory_files`.

Revision ID: 0065_agent_memory_fact_origin
Revises: 0064_agent_memory_facts
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0065_agent_memory_fact_origin"
down_revision: str | None = "0064_agent_memory_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fill existing rows with the conservative `agent` tier via a server default,
    # then drop it so the application sets `origin` explicitly on every write.
    op.add_column(
        "agent_memory_facts",
        sa.Column("origin", sa.String(length=16), nullable=False, server_default="agent"),
    )
    op.alter_column("agent_memory_facts", "origin", server_default=None)
    op.create_check_constraint(
        op.f("agent_memory_facts_ck_agent_memory_fact_origin_check"),
        "agent_memory_facts",
        "origin IN ('operator', 'agent')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("agent_memory_facts_ck_agent_memory_fact_origin_check"),
        "agent_memory_facts",
        type_="check",
    )
    op.drop_column("agent_memory_facts", "origin")
