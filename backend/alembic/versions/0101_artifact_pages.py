"""Artifacts: an environment in the identity, public link settings and embeds.

Three changes to `artifacts`, one per thing a page could not say before:

- `environment_id`: which named environment's runs publish the page (#1965).
  The identity was `(organization, agent, name)`, so a run in `staging`
  republished the page production readers had bookmarked. The unique constraint
  becomes a unique index over `coalesce(environment_id, <nil uuid>)`: a plain
  constraint treats every null as distinct, and the default environment has to
  be one slot. `agent_id` stays outside the coalesce on purpose - artifacts whose
  agent was deleted have no publisher, and any number of them may share a name.
  Every existing row was published without an environment, so every one lands in
  the default slot, which is exactly the uniqueness the old constraint enforced.
- `public_expires_at`, `public_version_number`, `public_password_hash`,
  `public_view_count`, `public_last_viewed_at`: the public link's settings and
  its counter (#1972). The pinned version is a number, not a foreign key, because
  `artifact_versions` already references this table. Existing rows take a count
  of zero and no settings, which is what they had.
- `embed_origins`: the sites allowed to frame the public page (#1973). Empty for
  every existing row: nothing was embeddable.

The downgrade restores the old constraint. It would fail on two pages of one name
in two environments of one agent, which is data only this revision can have made;
the downgrade deletes the named-environment rows first rather than guess which
one should keep the name - their versions go with them by cascade, and their
stored bytes stay orphaned under the artifact's prefix.

Revision ID: 0101_artifact_pages
Revises: 0100_directory_groups
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0101_artifact_pages"
down_revision: str | Sequence[str] | None = "0100_directory_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("environment_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("artifacts_environment_id_fkey"),
        "artifacts",
        "agent_environments",
        ["environment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("artifacts_environment_id_idx"), "artifacts", ["environment_id"], unique=False
    )
    op.drop_constraint("uq_artifact_org_agent_name", "artifacts", type_="unique")
    op.create_index(
        "uq_artifact_identity",
        "artifacts",
        [
            "organization_id",
            "agent_id",
            sa.text("coalesce(environment_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "name",
        ],
        unique=True,
    )

    op.add_column(
        "artifacts", sa.Column("public_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("artifacts", sa.Column("public_version_number", sa.Integer(), nullable=True))
    op.add_column(
        "artifacts", sa.Column("public_password_hash", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "artifacts",
        sa.Column("public_view_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "artifacts", sa.Column("public_last_viewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "artifacts",
        sa.Column(
            "embed_origins",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("artifacts_ck_artifact_public_view_count_check"),
        "artifacts",
        "public_view_count >= 0",
    )
    op.create_check_constraint(
        op.f("artifacts_ck_artifact_public_version_number_check"),
        "artifacts",
        "public_version_number IS NULL OR public_version_number >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("artifacts_ck_artifact_public_version_number_check"), "artifacts", type_="check"
    )
    op.drop_constraint(
        op.f("artifacts_ck_artifact_public_view_count_check"), "artifacts", type_="check"
    )
    op.drop_column("artifacts", "embed_origins")
    op.drop_column("artifacts", "public_last_viewed_at")
    op.drop_column("artifacts", "public_view_count")
    op.drop_column("artifacts", "public_password_hash")
    op.drop_column("artifacts", "public_version_number")
    op.drop_column("artifacts", "public_expires_at")

    op.execute("DELETE FROM artifacts WHERE environment_id IS NOT NULL")
    op.drop_index("uq_artifact_identity", table_name="artifacts")
    op.create_unique_constraint(
        "uq_artifact_org_agent_name", "artifacts", ["organization_id", "agent_id", "name"]
    )
    op.drop_index(op.f("artifacts_environment_id_idx"), table_name="artifacts")
    op.drop_constraint(op.f("artifacts_environment_id_fkey"), "artifacts", type_="foreignkey")
    op.drop_column("artifacts", "environment_id")
