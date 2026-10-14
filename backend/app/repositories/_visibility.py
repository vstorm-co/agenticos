"""The visibility disjunction skills and knowledge bases share.

A resource with an owner and a `visibility` is reachable three ways: it is the
caller's own, it is visible to the whole organization, or it was explicitly
shared with them. Written once because the copies drifted - one arm was Python
`False` where the others were SQL `false()` - and because a listing that
disagrees with the detail route it feeds shows a row in one and 404s in the
other (#545).
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, or_
from sqlalchemy.orm import InstrumentedAttribute

from app.core.permissions import Scope
from app.db.models.resource_grant import Visibility


def _org_visible_or_shared(
    visibility_col: InstrumentedAttribute[str],
    id_col: InstrumentedAttribute[UUID],
    *,
    shared_ids: Sequence[UUID],
) -> ColumnElement[bool]:
    """Org-visible, or in the set explicitly granted to the caller.

    `false()`, not Python `False`, for the empty-grant arm: it is a SQL literal
    like the others, so an empty grant list adds `OR false` rather than a bare
    Python constant the copies disagreed on.
    """
    return or_(
        visibility_col == Visibility.ORG.value,
        id_col.in_(shared_ids) if shared_ids else false(),
    )


def visible_to_caller(
    owner_col: InstrumentedAttribute[UUID | None],
    visibility_col: InstrumentedAttribute[str],
    id_col: InstrumentedAttribute[UUID],
    *,
    user_id: UUID,
    shared_ids: Sequence[UUID],
) -> ColumnElement[bool]:
    """Rows the caller may see: their own, org-visible, or shared with them.

    A team-visible row nobody granted stays invisible - "team" means named
    members, not everybody.
    """
    return or_(
        owner_col == user_id,
        _org_visible_or_shared(visibility_col, id_col, shared_ids=shared_ids),
    )


def shared_with_caller(
    owner_col: InstrumentedAttribute[UUID | None],
    visibility_col: InstrumentedAttribute[str],
    id_col: InstrumentedAttribute[UUID],
    *,
    user_id: UUID,
    shared_ids: Sequence[UUID],
) -> ColumnElement[bool]:
    """Rows shared *with* the caller: org-visible or granted, and not their own.

    `IS DISTINCT FROM`, not `!=`: an ownerless row is not the caller's.
    """
    return and_(
        _org_visible_or_shared(visibility_col, id_col, shared_ids=shared_ids),
        owner_col.is_distinct_from(user_id),
    )


def reached_by_scope(
    owner_col: InstrumentedAttribute[UUID | None],
    visibility_col: InstrumentedAttribute[str],
    id_col: InstrumentedAttribute[UUID],
    *,
    scope: Scope,
    user_id: UUID,
    granted_ids: Sequence[UUID],
) -> ColumnElement[bool]:
    """Rows a role scope reaches, or an explicit grant does - `resolve_access` as SQL.

    The scope arms mirror `_scope_allows` in `app/services/access.py`; the grant
    arm is the ids granted at the level the permission needs. `Scope.ALL` reaches
    every row, which the caller expresses by adding no condition at all.
    """
    granted = id_col.in_(granted_ids) if granted_ids else false()
    owned = and_(owner_col.is_not(None), owner_col == user_id)
    if scope is Scope.TEAM:
        reached = or_(owned, visibility_col.in_([Visibility.TEAM.value, Visibility.ORG.value]))
    elif scope is Scope.SHARED:
        reached = or_(owned, visibility_col == Visibility.ORG.value)
    elif scope is Scope.OWN:
        reached = owned
    else:
        reached = false()
    return or_(reached, granted)
