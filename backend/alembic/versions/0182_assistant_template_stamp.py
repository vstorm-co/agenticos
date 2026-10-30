"""Track the shipped Architect instructions without adopting organization edits.

Revision ID: 0182_assistant_template_stamp
Revises: 0181_attachment_lookup_marker
"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0182_assistant_template_stamp"
down_revision: str | None = "0181_attachment_lookup_marker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen hashes of instructions shipped before this migration. An unknown copy
# cannot safely be distinguished from an organization's deliberate customization.
SHIPPED = frozenset(
    (
        "21da9fb5fb2261b90828f4b2b36b4695317df0e15f4125e2b52f0823fd33d42b",
        "42df5e23c55f9029c5f4ba1aad786b6ea45db2240a4d46883c32af767cbc7f6e",
        "a23b7b27d4f9f5067b609724108839439c2226badd3fe30b55338771b4470c6e",
        "b2a36aa83e459dc187025262dd58199f8fd5c381dec952b886ee0dc18853ba72",
        "c5413021d5022b735c5538e2aad91c06c94691ffa7a0557000d2e6080ecbf7ae",
        "e8c58efc23f0240f9cfbfba5e954e6a33e9c11c7d6c391f9b7d8d800288df819",
        "edc222143f0fec6f048ce85d9eb91c6b8c87b73692f580212005c3ea412816db",
    )
)


def upgrade() -> None:
    op.add_column(
        "organization_assistants",
        sa.Column("instructions_fingerprint", sa.String(64), nullable=True),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("""
        SELECT oa.organization_id, a.draft_spec, av.spec
        FROM organization_assistants oa JOIN agents a ON a.id = oa.agent_id
        LEFT JOIN agent_versions av ON av.id = a.current_version_id
    """)
    )
    for row in rows:
        spec = row.spec if row.spec is not None else row.draft_spec
        digest = hashlib.sha256(spec.get("instructions", "").strip().encode()).hexdigest()
        if digest in SHIPPED:
            connection.execute(
                sa.text(
                    "UPDATE organization_assistants SET instructions_fingerprint = :digest WHERE organization_id = :id"
                ),
                {"digest": digest, "id": row.organization_id},
            )


def downgrade() -> None:
    op.drop_column("organization_assistants", "instructions_fingerprint")
