"""Record which skills a run used, and say which runs were never recorded.

Improving a skill reads the answers in which the skill was actually used. The
transcript already holds a `load_capability` call for every skill a model opened,
but by name, only where a transcript was written, and with nothing to tell a run
that used no skill from a run nobody recorded. `run_skill_uses` is written by the
runner itself, on every way a run ends, by skill id.

`agent_runs.skill_uses_recorded` is added false - every existing run is "usage
unknown" - and only then given its default of true, so the boundary is this
deployment's own upgrade rather than a date somebody guessed. Both steps change
the catalogue only; neither rewrites the table. It is nullable: the runner
inserts a run null, "not written yet", and a run stays false once any of its
segments could not be written.

The backfill copies what the transcripts prove: completed `load_capability` and
`read_skill_resource` calls - one that failed, waits for approval or was
rejected never opened the skill - and the `load_skill` calls made before skills became
deferred capabilities, whose argument was the name under either of two keys. A
name is matched to the skill of that name in the run's organization that already
existed when the run started, so a name taken again later is not credited to the
newer skill. The runs stay "unknown": an old transcript proves a load, never the
absence of one.

`skill_version_id` has no foreign key yet: skill versions do not exist at this
revision. The revision that adds them adds the key.

Plan a window for it on a large deployment: the new column takes an exclusive
lock on `agent_runs`, held until the backfill has read every row of
`tool_calls`, which has no index on the tool's name.

Revision ID: 0305_run_skill_uses
Revises: 0306_shared_page_attribution
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0305_run_skill_uses"
down_revision: str | None = "0306_shared_page_attribution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "skill_uses_recorded", sa.Boolean(), nullable=True, server_default=sa.text("false")
        ),
    )
    op.alter_column("agent_runs", "skill_uses_recorded", server_default=sa.text("true"))

    op.create_table(
        "run_skill_uses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("projected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("loaded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("resource_reads", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("workspace_reads", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("run_skill_uses_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("run_skill_uses_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("run_skill_uses_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name=op.f("run_skill_uses_skill_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("run_skill_uses_pkey")),
        sa.UniqueConstraint(
            "run_id", "agent_id", "skill_id", name="uq_run_skill_uses_run_agent_skill"
        ),
    )
    op.create_index(
        "ix_run_skill_uses_skill", "run_skill_uses", ["skill_id", "created_at"], unique=False
    )
    op.create_index("ix_run_skill_uses_agent", "run_skill_uses", ["agent_id"], unique=False)
    op.create_index(
        "ix_run_skill_uses_organization", "run_skill_uses", ["organization_id"], unique=False
    )

    op.execute(
        """
        INSERT INTO run_skill_uses (
            id, organization_id, run_id, agent_id, skill_id,
            loaded, resource_reads, created_at
        )
        SELECT
            gen_random_uuid(), r.organization_id, r.id, r.agent_id, s.id,
            bool_or(c.tool_name IN ('load_capability', 'load_skill')),
            count(*) FILTER (WHERE c.tool_name = 'read_skill_resource'),
            coalesce(r.started_at, r.created_at)
        FROM tool_calls c
        JOIN messages m ON m.id = c.message_id
        JOIN agent_runs r ON r.id = m.run_id
        JOIN skills s
          ON s.organization_id = r.organization_id
         AND s.created_at <= coalesce(r.started_at, r.created_at)
         AND s.name = CASE c.tool_name
                WHEN 'load_capability' THEN c.args->>'id'
                WHEN 'load_skill' THEN coalesce(c.args->>'skill_name', c.args->>'name')
                ELSE c.args->>'skill_name'
             END
        WHERE c.tool_name IN ('load_capability', 'load_skill', 'read_skill_resource')
          AND c.status = 'completed'
        GROUP BY r.organization_id, r.id, r.agent_id, s.id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_run_skill_uses_organization", table_name="run_skill_uses")
    op.drop_index("ix_run_skill_uses_agent", table_name="run_skill_uses")
    op.drop_index("ix_run_skill_uses_skill", table_name="run_skill_uses")
    op.drop_table("run_skill_uses")
    op.drop_column("agent_runs", "skill_uses_recorded")
