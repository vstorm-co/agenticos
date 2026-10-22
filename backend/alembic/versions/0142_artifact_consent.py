"""A page owner's consent to share the data a page version reads.

A bound page's data is read with its owner's access, and everyone who opens the
page reads the same records. Sharing those records beyond the owner and the roles
that read every table is the owner's decision, made per version: consent is to a
page query, and a republish that changes it asks again.

`artifact_versions` gains who published the version (the person and the
membership they acted under), the digest of its page queries
(`query_fingerprint`, null when it has none), and where it stands:
`consent_state`, when and by whom it was consented, under which of the owner's
memberships, and whether automatically. Columns rather than a key inside
`bindings`: an unchanged republish compares `bindings` and a restore copies them,
and neither may carry a consent along. `consent_via_grant` is for the `edit_data`
grant level, which a later revision adds; nothing writes it yet.

`consented_by_membership_id` and `published_by_membership_id` are plain ids, not
keys: removing and re-inviting the owner makes a new membership, and the consents
given under the old one must stay void rather than be deleted with it. A CHECK
holds a consented row to naming one.

`ix_artifact_versions_served` is the audience's read: the newest version that is
`consented` or `not_needed`, per page.

`artifacts` gains `auto_consent` (off) and `consent_withdrawn_at`: a withdrawal is
a cut-off that voids every consent given before it, on every version, in one write.

**Backfill.** A version with bindings published before this revision was never
consented to, so it becomes `pending` with its digest filled in - the default
`not_needed` would have handed its data to everyone who opens the page. The
digest is computed here by the formula `app.services.artifact_bindings.
fingerprint` uses (SHA-256 over the bindings sorted by name, keys sorted, compact
separators), written out rather than imported because a revision must not change
when the application does. Every other version is `not_needed`, which it is.

Revision ID: 0142_artifact_consent
Revises: 0141_approval_capability_tool
Create Date: 2026-10-22
"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0142_artifact_consent"
down_revision: str | None = "0141_approval_capability_tool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATE_CHECK = "artifact_versions_ck_artifact_version_consent_state_check"
_MEMBERSHIP_CHECK = "artifact_versions_ck_artifact_version_consent_membership_check"
_SERVED_INDEX = "ix_artifact_versions_served"
_USER_KEYS = ("published_by_user_id", "consented_by_user_id", "consent_via_grant")


def _fingerprint(bindings: list[dict[str, object]]) -> str:
    canonical = sorted(bindings, key=lambda binding: str(binding["name"]))
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.add_column(
        "artifacts",
        sa.Column("auto_consent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "artifacts",
        sa.Column("consent_withdrawn_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in (
        sa.Column("published_by_user_id", uuid, nullable=True),
        sa.Column("published_by_membership_id", uuid, nullable=True),
        sa.Column("query_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "consent_state", sa.String(length=16), nullable=False, server_default="not_needed"
        ),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consented_by_user_id", uuid, nullable=True),
        sa.Column("consented_by_membership_id", uuid, nullable=True),
        sa.Column("consent_automatic", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("consent_via_grant", uuid, nullable=True),
    ):
        op.add_column("artifact_versions", column)
    for name in _USER_KEYS:
        op.create_foreign_key(
            op.f(f"artifact_versions_{name}_fkey"),
            "artifact_versions",
            "users",
            [name],
            ["id"],
            ondelete="SET NULL",
        )

    connection = op.get_bind()
    bound = connection.execute(
        sa.text("SELECT id, bindings FROM artifact_versions WHERE bindings <> '[]'::jsonb")
    ).all()
    for version_id, bindings in bound:
        connection.execute(
            sa.text(
                "UPDATE artifact_versions SET consent_state = 'pending', "
                "query_fingerprint = :fingerprint WHERE id = :id"
            ),
            {"id": version_id, "fingerprint": _fingerprint(bindings)},
        )

    op.create_check_constraint(
        op.f(_STATE_CHECK),
        "artifact_versions",
        "consent_state IN ('not_needed', 'pending', 'consented', 'declined', 'withdrawn')",
    )
    op.create_check_constraint(
        op.f(_MEMBERSHIP_CHECK),
        "artifact_versions",
        "consent_state <> 'consented' OR consented_by_membership_id IS NOT NULL",
    )
    op.create_index(
        _SERVED_INDEX,
        "artifact_versions",
        ["artifact_id", sa.text("number DESC")],
        postgresql_where=sa.text("consent_state IN ('consented', 'not_needed')"),
    )


def downgrade() -> None:
    op.drop_index(_SERVED_INDEX, table_name="artifact_versions")
    op.drop_constraint(op.f(_MEMBERSHIP_CHECK), "artifact_versions", type_="check")
    op.drop_constraint(op.f(_STATE_CHECK), "artifact_versions", type_="check")
    for name in _USER_KEYS:
        op.drop_constraint(
            op.f(f"artifact_versions_{name}_fkey"), "artifact_versions", type_="foreignkey"
        )
    for name in (
        "consent_via_grant",
        "consent_automatic",
        "consented_by_membership_id",
        "consented_by_user_id",
        "consented_at",
        "consent_state",
        "query_fingerprint",
        "published_by_membership_id",
        "published_by_user_id",
    ):
        op.drop_column("artifact_versions", name)
    op.drop_column("artifacts", "consent_withdrawn_at")
    op.drop_column("artifacts", "auto_consent")
