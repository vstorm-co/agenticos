"""Data access for the deployment's single settings row (PostgreSQL async).

There is no tenant predicate here and deliberately no way to add one: the row
describes the installation, not an organization, and every caller is the same
caller. What the queries do carry is the singleton guarantee - the write is one
atomic `INSERT ... ON CONFLICT DO UPDATE` on the unique constraint, because a
read-then-insert races itself the moment two administrators save from two tabs
and the loser gets an `IntegrityError` no handler translates.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.deployment_settings import SIGNUP_CONSTRAINT, DeploymentSettings


async def get(db: AsyncSession) -> DeploymentSettings | None:
    """The settings row, or `None` when nothing has ever been configured.

    `None` is not an error. It is the state of every deployment before an
    administrator first saves, and it means "every built-in default" - which is
    why no read path here creates a row.
    """
    result = await db.execute(select(DeploymentSettings))
    return result.scalar_one_or_none()


async def upsert(db: AsyncSession, *, update_data: dict[str, Any]) -> DeploymentSettings:
    """Write the given columns, creating the row when there is none.

    `updated_at` is set explicitly: the model's `onupdate` fires on an ORM flush
    and this is a Core upsert, so without it a replaced logo would keep the
    version token its cache-busting URL is built from.

    `populate_existing` is load-bearing, and its absence was a real defect. When
    the session has already loaded this row - which `set_image` and `clear_image`
    both do, to find the file they are replacing - the identity map wins:
    `RETURNING` yields that same instance carrying its *old* attribute values, and
    so does any later `select` in the same session. The upload then answered
    `logo_version: null` for a logo it had just stored and was already serving the
    bytes of. No unit test could see it, because they all mock this module;
    `tests/integration/test_deployment_settings_row.py` is what holds it shut.
    """
    stmt = (
        insert(DeploymentSettings)
        .values(singleton=True, **update_data)
        .on_conflict_do_update(
            constraint=SIGNUP_CONSTRAINT,
            set_={**update_data, "updated_at": func.now()},
        )
        .returning(DeploymentSettings)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()
