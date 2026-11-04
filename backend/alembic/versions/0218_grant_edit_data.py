"""A grant level above `edit`, for pages only: `edit_data` (#1974).

"Can edit, data included" is `edit` plus the owner's standing consent to that editor's
(or group's) republishes of a page that reads live data. `GRANT_ORDER` ranks it above
`edit`, so every check that asks for `edit` is met by it.

`ck_resource_grant_level` admits the new value, and a second CHECK,
`ck_resource_grant_edit_data_artifact`, keeps it to pages: no other resource type has a
data owner to consent, and a grant there would read as an edit that means more than it does.

The downgrade rewrites every `edit_data` grant to `edit` rather than deleting it: the
person keeps what they could always do, and only the standing consent goes.

Revision ID: 0218_grant_edit_data
Revises: 0217_artifact_share_requests
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0218_grant_edit_data"
down_revision: str | Sequence[str] | None = "0217_artifact_share_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEVEL = "ck_resource_grant_level"
_GUARD = "ck_resource_grant_edit_data_artifact"


def _recreate_level(values: str) -> None:
    op.drop_constraint(_LEVEL, "resource_grants", type_="check")
    op.create_check_constraint(_LEVEL, "resource_grants", f"level IN ({values})")


def upgrade() -> None:
    _recreate_level("'read', 'use', 'edit', 'edit_data'")
    op.create_check_constraint(
        _GUARD, "resource_grants", "level <> 'edit_data' OR resource_type = 'artifact'"
    )


def downgrade() -> None:
    op.drop_constraint(_GUARD, "resource_grants", type_="check")
    op.execute("UPDATE resource_grants SET level = 'edit' WHERE level = 'edit_data'")
    _recreate_level("'read', 'use', 'edit'")
