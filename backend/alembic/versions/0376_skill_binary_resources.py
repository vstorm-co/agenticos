"""Preserve binary skill assets while retaining all existing text version hashes.

Live rows distinguish exact UTF-8 from canonical base64. Immutable version
manifests add optional encoding metadata; absent metadata continues to mean
UTF-8, so no existing version or content-addressed file is rewritten. File
bodies remain deduplicated by the SHA-256 of their decoded bytes. A downgrade
refuses binary data rather than relabeling it as text or silently dropping it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0376_skill_binary_resources"
down_revision: str = "0375_merge_service_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skill_checks",
        sa.Column(
            "candidate_manifest_metadata", postgresql.JSONB(none_as_null=True), nullable=True
        ),
    )
    op.create_check_constraint(
        op.f("skill_checks_ck_skill_check_manifest_metadata"),
        "skill_checks",
        "candidate_manifest_metadata IS NULL OR jsonb_typeof(candidate_manifest_metadata) = 'object'",
    )
    for table in ("skills", "skill_versions"):
        op.add_column(
            table,
            sa.Column(
                "manifest_metadata",
                postgresql.JSONB(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )
        op.create_check_constraint(
            op.f(f"{table}_ck_{table}_manifest_metadata_check"),
            table,
            "jsonb_typeof(manifest_metadata) = 'object'",
        )
    op.add_column(
        "skill_resources",
        sa.Column("encoding", sa.String(length=8), server_default="utf8", nullable=False),
    )
    op.create_check_constraint(
        op.f("skill_resources_ck_skill_resource_encoding_check"),
        "skill_resources",
        "encoding IN ('utf8', 'base64')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM skill_resources WHERE encoding = 'base64') "
            "OR EXISTS (SELECT 1 FROM skill_versions v, "
            "jsonb_each(v.resources) entry WHERE entry.value->>'encoding' = 'base64') "
            "OR EXISTS (SELECT 1 FROM skills WHERE manifest_metadata <> '{}'::jsonb) "
            "OR EXISTS (SELECT 1 FROM skill_versions WHERE manifest_metadata <> '{}'::jsonb) "
            "OR EXISTS (SELECT 1 FROM skill_checks WHERE candidate_manifest_metadata IS NOT NULL AND candidate_manifest_metadata <> '{}'::jsonb)"
        )
    ).scalar_one():
        raise RuntimeError(
            "Binary skill files or preserved frontmatter exist. Export and explicitly remove "
            "those skills before downgrading; bytes and frontmatter cannot be discarded."
        )
    op.drop_constraint(
        op.f("skill_checks_ck_skill_check_manifest_metadata"), "skill_checks", type_="check"
    )
    op.drop_column("skill_checks", "candidate_manifest_metadata")
    for table in ("skill_versions", "skills"):
        op.drop_constraint(
            op.f(f"{table}_ck_{table}_manifest_metadata_check"), table, type_="check"
        )
        op.drop_column(table, "manifest_metadata")
    op.drop_constraint(
        op.f("skill_resources_ck_skill_resource_encoding_check"), "skill_resources", type_="check"
    )
    op.drop_column("skill_resources", "encoding")
