"""Catch skills up with main: what a version took in, and where a fork started.

Catching a fork up with main makes a fork version that takes main's newest in, and
the fork is based on that main version from then on. Moving a fork's changes to main
makes a main version that takes the fork's in. `skill_versions.merged_from_id` names
the other line's version a version took in, and two new sources say which way it went.

A catch-up moves `skill_forks.base_version_id`, so `started_from_id` keeps the main
version a fork was started from: the fork's first version still came after it. It is
backfilled from the base, which no fork has moved yet.

A pinned agent catches up by a check on that one agent: `skill_checks.agent_id` names
it, `candidate_version_id` the main version it would move to, and the source
`catch_up` says so.

**Downgrade** forgets which versions were merges - their source reads `edit` - and a
fork stays based where its last catch-up left it. A pinned agent's checks are
deleted: the older schema has no way to say which agent one was for.

Revision ID: 0253_skill_catch_up
Revises: 0252_skill_improvement_sessions
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0253_skill_catch_up"
down_revision: str | Sequence[str] | None = "0252_skill_improvement_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCES = (
    "'backfill', 'created', 'edit', 'resources', 'library', 'workspace', 'improve', 'restore'"
)
_CHECK = "skill_versions_ck_skill_version_source_check"
_CHECK_SOURCES = "'manual', 'proposal', 'session'"
_CHECK_SOURCE = "skill_checks_ck_skill_check_source_check"


def upgrade() -> None:
    op.add_column("skill_versions", sa.Column("merged_from_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("skill_versions_merged_from_id_fkey"),
        "skill_versions",
        "skill_versions",
        ["merged_from_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("skill_versions_merged_from_id_idx"),
        "skill_versions",
        ["merged_from_id"],
        unique=False,
    )
    op.drop_constraint(op.f(_CHECK), "skill_versions", type_="check")
    op.create_check_constraint(
        op.f(_CHECK), "skill_versions", f"source IN ({_SOURCES}, 'catch_up', 'from_fork')"
    )

    op.add_column("skill_forks", sa.Column("started_from_id", sa.UUID(), nullable=True))
    op.execute("UPDATE skill_forks SET started_from_id = base_version_id")
    op.alter_column("skill_forks", "started_from_id", nullable=False)
    op.create_foreign_key(
        op.f("skill_forks_started_from_id_fkey"),
        "skill_forks",
        "skill_versions",
        ["started_from_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("skill_forks_started_from_id_idx"), "skill_forks", ["started_from_id"], unique=False
    )

    op.add_column("skill_checks", sa.Column("agent_id", sa.UUID(), nullable=True))
    op.add_column("skill_checks", sa.Column("candidate_version_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("skill_checks_agent_id_fkey"),
        "skill_checks",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("skill_checks_candidate_version_id_fkey"),
        "skill_checks",
        "skill_versions",
        ["candidate_version_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_skill_checks_agent", "skill_checks", ["agent_id"], unique=False)
    op.create_index(
        "ix_skill_checks_candidate_version", "skill_checks", ["candidate_version_id"], unique=False
    )
    op.drop_constraint(op.f(_CHECK_SOURCE), "skill_checks", type_="check")
    op.create_check_constraint(
        op.f(_CHECK_SOURCE), "skill_checks", f"source IN ({_CHECK_SOURCES}, 'catch_up')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM skill_checks WHERE source = 'catch_up'")
    op.drop_constraint(op.f(_CHECK_SOURCE), "skill_checks", type_="check")
    op.create_check_constraint(op.f(_CHECK_SOURCE), "skill_checks", f"source IN ({_CHECK_SOURCES})")
    op.drop_index("ix_skill_checks_candidate_version", table_name="skill_checks")
    op.drop_index("ix_skill_checks_agent", table_name="skill_checks")
    op.drop_constraint(
        op.f("skill_checks_candidate_version_id_fkey"), "skill_checks", type_="foreignkey"
    )
    op.drop_constraint(op.f("skill_checks_agent_id_fkey"), "skill_checks", type_="foreignkey")
    op.drop_column("skill_checks", "candidate_version_id")
    op.drop_column("skill_checks", "agent_id")

    op.drop_index(op.f("skill_forks_started_from_id_idx"), table_name="skill_forks")
    op.drop_constraint(op.f("skill_forks_started_from_id_fkey"), "skill_forks", type_="foreignkey")
    op.drop_column("skill_forks", "started_from_id")

    _forget_merges()
    op.drop_constraint(op.f(_CHECK), "skill_versions", type_="check")
    op.create_check_constraint(op.f(_CHECK), "skill_versions", f"source IN ({_SOURCES})")
    op.drop_index(op.f("skill_versions_merged_from_id_idx"), table_name="skill_versions")
    op.drop_constraint(
        op.f("skill_versions_merged_from_id_fkey"), "skill_versions", type_="foreignkey"
    )
    op.drop_column("skill_versions", "merged_from_id")


def _forget_merges() -> None:
    """Read every merge as an edit, which is all the older schema can say."""
    op.execute(
        "UPDATE skill_versions SET source = 'edit' WHERE source IN ('catch_up', 'from_fork')"
    )
