"""Version skills: immutable versions on a main line and on forks.

A skill was one live row. An edit reached every agent at once, including agents that
never saw it tested, and nothing recorded what the skill said before. This revision
adds `skill_versions`, never updated once written and numbered per line, the
`skill_forks` they may belong to, and `skill_files`, the file bodies a version's
manifest names by content hash, stored once per skill.

The `skills` row keeps its columns as a mirror of the newest main version, pointed
at by the new `latest_version_id`, so every reader written before versions still
reads the text an agent on main gets. `uq_skills_tenant` is the target of the new
tables' `(skill_id, organization_id)` keys, which keep a version, a fork or a file
in its skill's organization by schema rather than by every writer.

`skill_proposals` gains `base_version_id` and `fork_id`: the exact version a change
was written against and the line it is for. `agent_runs.skill_version_ids` records
the versions a run served, and `run_skill_uses.skill_version_id`, kept without a key
by the revision before this one, gets its key to `skill_versions`.

**Backfill.** Each skill's text and files as they stand become its main v1, with
source `backfill` - earlier texts were never kept, so there is nothing truer to
record. `skills.version` restarts at 1 to match. A pending proposal written against
the version the skill is at now is re-pointed at v1; any other pending proposal was
written against a text that is gone, keeps its old number and no `base_version_id`,
and is refused on apply as written against a skill that has moved. Re-numbering it
instead would let an old proposal with `base_version = 1` overwrite the backfilled
v1 as if nothing had changed. A skill whose organization is gone - a row written
past its keys - is left without a version rather than failing the upgrade.

**Downgrade** drops the history: the skills keep the text of their newest main
version and its number. Specs written by the binding that comes with versions
(`skill_bindings`) lose it, so every agent reads its skills' main text again. The
skill uses recorded since keep their rows and lose the version they were served.
A change still waiting for a fork is discarded: without its fork it would read as a
change to main, and applying it would put the fork's text on main.

Revision ID: 0306_skill_versions
Revises: 0305_run_skill_uses
Create Date: 2026-11-02
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0306_skill_versions"
down_revision: str | Sequence[str] | None = "0305_run_skill_uses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCES = (
    "'backfill', 'created', 'edit', 'resources', 'library', 'workspace', 'improve', 'restore'"
)

_SHA = "encode(sha256(convert_to(r.content, 'UTF8')), 'hex')"


def upgrade() -> None:
    op.create_unique_constraint("uq_skills_tenant", "skills", ["id", "organization_id"])
    op.add_column("skills", sa.Column("latest_version_id", sa.UUID(), nullable=True))

    op.create_table(
        "skill_forks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("base_version_id", sa.UUID(), nullable=False),
        sa.Column("latest_version_id", sa.UUID(), nullable=True),
        sa.Column("created_for_agent_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["archived_by_user_id"],
            ["users.id"],
            name=op.f("skill_forks_archived_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("skill_forks_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_for_agent_id"],
            ["agents.id"],
            name=op.f("skill_forks_created_for_agent_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("skill_forks_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            name=op.f("skill_forks_skill_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("skill_forks_pkey")),
        sa.UniqueConstraint("id", "organization_id", name="uq_skill_forks_tenant"),
        sa.UniqueConstraint("skill_id", "name", name="uq_skill_forks_name"),
    )
    op.create_index(
        op.f("skill_forks_organization_id_idx"), "skill_forks", ["organization_id"], unique=False
    )

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("fork_id", sa.UUID(), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "resources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("restored_from_id", sa.UUID(), nullable=True),
        sa.Column("proposal_id", sa.UUID(), nullable=True),
        sa.Column("library_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"source IN ({_SOURCES})", name=op.f("skill_versions_ck_skill_version_source_check")
        ),
        sa.CheckConstraint(
            "number >= 1", name=op.f("skill_versions_ck_skill_version_number_check")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("skill_versions_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fork_id", "organization_id"],
            ["skill_forks.id", "skill_forks.organization_id"],
            name=op.f("skill_versions_fork_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("skill_versions_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["skill_proposals.id"],
            name=op.f("skill_versions_proposal_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["restored_from_id"],
            ["skill_versions.id"],
            name=op.f("skill_versions_restored_from_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            name=op.f("skill_versions_skill_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("skill_versions_pkey")),
        sa.UniqueConstraint("id", "organization_id", name="uq_skill_versions_tenant"),
    )
    op.create_index(
        "ix_skill_versions_skill",
        "skill_versions",
        ["organization_id", "skill_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_skill_versions_fork_number",
        "skill_versions",
        ["fork_id", "number"],
        unique=True,
        postgresql_where=sa.text("fork_id IS NOT NULL"),
    )
    op.create_index(
        "uq_skill_versions_main_number",
        "skill_versions",
        ["skill_id", "number"],
        unique=True,
        postgresql_where=sa.text("fork_id IS NULL"),
    )

    op.create_table(
        "skill_files",
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("skill_files_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            name=op.f("skill_files_skill_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("skill_id", "sha256", name=op.f("skill_files_pkey")),
    )

    op.create_foreign_key(
        op.f("skill_forks_base_version_id_fkey"),
        "skill_forks",
        "skill_versions",
        ["base_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("skill_forks_latest_version_id_fkey"),
        "skill_forks",
        "skill_versions",
        ["latest_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("skills_latest_version_id_fkey"),
        "skills",
        "skill_versions",
        ["latest_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("skill_proposals", sa.Column("base_version_id", sa.UUID(), nullable=True))
    op.add_column("skill_proposals", sa.Column("fork_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("skill_proposals_base_version_id_fkey"),
        "skill_proposals",
        "skill_versions",
        ["base_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("skill_proposals_fork_id_fkey"),
        "skill_proposals",
        "skill_forks",
        ["fork_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "agent_runs", sa.Column("skill_version_ids", postgresql.ARRAY(sa.UUID()), nullable=True)
    )
    op.create_foreign_key(
        op.f("run_skill_uses_skill_version_id_fkey"),
        "run_skill_uses",
        "skill_versions",
        ["skill_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Deleting a skill cascades through these keys, and deleting a version or a fork
    # sets them; unindexed, each would scan the whole table it sits in.
    op.create_index(
        op.f("skill_forks_base_version_id_idx"), "skill_forks", ["base_version_id"], unique=False
    )
    op.create_index(
        op.f("skill_forks_latest_version_id_idx"),
        "skill_forks",
        ["latest_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_versions_restored_from_id_idx"),
        "skill_versions",
        ["restored_from_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_versions_proposal_id_idx"), "skill_versions", ["proposal_id"], unique=False
    )
    op.create_index(
        op.f("skill_proposals_base_version_id_idx"),
        "skill_proposals",
        ["base_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_proposals_fork_id_idx"), "skill_proposals", ["fork_id"], unique=False
    )
    op.create_index(
        op.f("run_skill_uses_skill_version_id_idx"),
        "run_skill_uses",
        ["skill_version_id"],
        unique=False,
    )

    _backfill()


def _backfill() -> None:
    op.execute(
        f"""
        INSERT INTO skill_files (skill_id, sha256, organization_id, content)
        SELECT DISTINCT ON (r.skill_id, {_SHA}) r.skill_id, {_SHA}, s.organization_id, r.content
        FROM skill_resources r
        JOIN skills s ON s.id = r.skill_id
        JOIN organizations o ON o.id = s.organization_id
        """
    )
    op.execute(
        f"""
        INSERT INTO skill_versions (
            id, organization_id, skill_id, number, description, content, resources,
            source, library_fingerprint, created_at
        )
        SELECT
            gen_random_uuid(), s.organization_id, s.id, 1, s.description, s.content,
            COALESCE(
                (
                    SELECT jsonb_object_agg(
                        r.name,
                        jsonb_build_object(
                            'sha256', {_SHA},
                            'description', r.description,
                            'size_bytes', octet_length(convert_to(r.content, 'UTF8'))
                        )
                    )
                    FROM skill_resources r WHERE r.skill_id = s.id
                ),
                '{{}}'::jsonb
            ),
            'backfill', s.library_fingerprint, COALESCE(s.updated_at, s.created_at)
        FROM skills s JOIN organizations o ON o.id = s.organization_id
        """
    )
    # Before `skills.version` restarts: the comparison is with the number it has now.
    op.execute(
        """
        UPDATE skill_proposals p
        SET base_version = 1, base_version_id = v.id
        FROM skills s JOIN skill_versions v ON v.skill_id = s.id AND v.fork_id IS NULL
        WHERE p.skill_id = s.id AND p.status = 'pending' AND p.base_version = s.version
        """
    )
    op.execute(
        """
        UPDATE skills s SET version = 1, latest_version_id = v.id
        FROM skill_versions v WHERE v.skill_id = s.id AND v.fork_id IS NULL
        """
    )


def _without_bindings(spec: Any) -> Any:
    """The spec without `skill_bindings`, its own or any inline specialist's."""
    if isinstance(spec, dict):
        return {
            key: _without_bindings(value) for key, value in spec.items() if key != "skill_bindings"
        }
    if isinstance(spec, list):
        return [_without_bindings(item) for item in spec]
    return spec


def _strip_bindings(table: str, column: str) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"SELECT id, {column} FROM {table} WHERE {column}::text LIKE '%\"skill_bindings\"%'"
        )
    ).all()
    for row_id, spec in rows:
        connection.execute(
            sa.text(f"UPDATE {table} SET {column} = CAST(:spec AS jsonb) WHERE id = :id"),
            {"spec": json.dumps(_without_bindings(spec)), "id": row_id},
        )


_STORED_SPECS = (
    ("agents", "draft_spec"),
    ("agent_versions", "spec"),
    ("agent_runs", "test_spec"),
    ("eval_run_arms", "spec"),
)
"""Every column holding a whole agent spec, each of which the older code validates
again: a parked test run resumed, an eval arm run again."""


def _strip_every_binding() -> None:
    for table, column in _STORED_SPECS:
        _strip_bindings(table, column)


def _discard_fork_proposals() -> None:
    op.execute(
        "UPDATE skill_proposals SET status = 'discarded', decided_at = now(), "
        "revision = revision + 1 WHERE fork_id IS NOT NULL AND status = 'pending'"
    )


def downgrade() -> None:
    _strip_every_binding()
    _discard_fork_proposals()

    _forget_served_versions()
    op.drop_index(op.f("run_skill_uses_skill_version_id_idx"), table_name="run_skill_uses")
    op.drop_constraint(
        op.f("run_skill_uses_skill_version_id_fkey"), "run_skill_uses", type_="foreignkey"
    )
    op.drop_column("agent_runs", "skill_version_ids")
    op.drop_index(op.f("skill_forks_base_version_id_idx"), table_name="skill_forks")
    op.drop_index(op.f("skill_forks_latest_version_id_idx"), table_name="skill_forks")
    op.drop_index(op.f("skill_versions_restored_from_id_idx"), table_name="skill_versions")
    op.drop_index(op.f("skill_versions_proposal_id_idx"), table_name="skill_versions")
    op.drop_index(op.f("skill_proposals_base_version_id_idx"), table_name="skill_proposals")
    op.drop_index(op.f("skill_proposals_fork_id_idx"), table_name="skill_proposals")
    op.drop_constraint(op.f("skill_proposals_fork_id_fkey"), "skill_proposals", type_="foreignkey")
    op.drop_constraint(
        op.f("skill_proposals_base_version_id_fkey"), "skill_proposals", type_="foreignkey"
    )
    op.drop_column("skill_proposals", "fork_id")
    op.drop_column("skill_proposals", "base_version_id")

    op.drop_constraint(op.f("skills_latest_version_id_fkey"), "skills", type_="foreignkey")
    op.drop_constraint(
        op.f("skill_forks_latest_version_id_fkey"), "skill_forks", type_="foreignkey"
    )
    op.drop_constraint(op.f("skill_forks_base_version_id_fkey"), "skill_forks", type_="foreignkey")
    op.drop_table("skill_files")
    op.drop_index(
        "uq_skill_versions_main_number",
        table_name="skill_versions",
        postgresql_where=sa.text("fork_id IS NULL"),
    )
    op.drop_index(
        "uq_skill_versions_fork_number",
        table_name="skill_versions",
        postgresql_where=sa.text("fork_id IS NOT NULL"),
    )
    op.drop_index("ix_skill_versions_skill", table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_index(op.f("skill_forks_organization_id_idx"), table_name="skill_forks")
    op.drop_table("skill_forks")
    op.drop_column("skills", "latest_version_id")
    op.drop_constraint("uq_skills_tenant", "skills", type_="unique")


def _forget_served_versions() -> None:
    """Clear the version each skill use was served: the column outlives the versions it
    names, and an id of a version that is gone would read as one that exists."""
    op.execute("UPDATE run_skill_uses SET skill_version_id = NULL")
