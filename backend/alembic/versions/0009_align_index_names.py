"""Rename the indexes 0002-0004 named the old way

Revision ID: 0009_align_index_names
Revises: 0008_approval_delegate
Create Date: 2026-08-05

`0001_baseline` moved every index name onto `Base.metadata.naming_convention`
(`<table>_<col>_idx`) to end the drift that made `alembic revision --autogenerate`
emit four hundred lines of noise. The three migrations added after the squash -
`0002_agent_workspaces`, `0003_sandbox_connections`, `0004_skill_proposals` -
reintroduced exactly that noise: each wrote `op.create_index(op.f("ix_<table>_<col>"))`,
the hand-written `ix_*` of the old chain, while the models declare `index=True` and so
resolve to `<table>_<col>_idx`. Twelve indexes disagreed with the models, so
`alembic check` failed on `main` for reasons unrelated to any change under test - which
is why it could not be added to `make check` as the gate that catches "a model changed
and the migration did not".

This renames those twelve to what the models declare. A rename, not a drop-and-create:
the index is preserved, and the name is the only thing wrong. The composite
`ix_skill_proposals_pending` is *not* touched - the model names it explicitly, so the
database already agrees with it.

`ALTER INDEX ... RENAME TO ...` is a catalog-only operation in PostgreSQL - no rebuild,
no lock beyond the brief one it takes on the index. `downgrade()` restores the old
names so the chain round-trips.
"""

from alembic import op

# (old ix_* name, convention <table>_<col>_idx name) for the twelve indexes that
# migrations 0002-0004 created under the pre-baseline naming.
RENAMES: list[tuple[str, str]] = [
    ("ix_agent_workspaces_agent_id", "agent_workspaces_agent_id_idx"),
    ("ix_agent_workspaces_connection_id", "agent_workspaces_connection_id_idx"),
    ("ix_agent_workspaces_conversation_id", "agent_workspaces_conversation_id_idx"),
    ("ix_agent_workspaces_organization_id", "agent_workspaces_organization_id_idx"),
    ("ix_agent_workspaces_owner_ref", "agent_workspaces_owner_ref_idx"),
    ("ix_agent_workspaces_scope_key", "agent_workspaces_scope_key_idx"),
    ("ix_sandbox_connections_organization_id", "sandbox_connections_organization_id_idx"),
    ("ix_sandbox_connections_secret_id", "sandbox_connections_secret_id_idx"),
    ("ix_skill_proposals_agent_id", "skill_proposals_agent_id_idx"),
    ("ix_skill_proposals_organization_id", "skill_proposals_organization_id_idx"),
    ("ix_skill_proposals_skill_id", "skill_proposals_skill_id_idx"),
    ("ix_skill_proposals_status", "skill_proposals_status_idx"),
]

revision = "0009_align_index_names"
down_revision = "0008_approval_delegate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for old_name, new_name in RENAMES:
        op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")


def downgrade() -> None:
    for old_name, new_name in RENAMES:
        op.execute(f"ALTER INDEX {new_name} RENAME TO {old_name}")
