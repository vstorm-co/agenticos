"""Saved views over a table's records: create, list, update, delete.

A view is a sub-resource of one table, not a shareable resource of its own - it has
no `ResourceType`, no grant subject, and "shared" means only "visible to anyone who
already has `tables:view` on the parent table" (`docs/virtual-tables.md`). Listing
and reading resolve against the table (`_load_table`); changing or deleting a view
additionally requires being its owner, or holding a `tables:edit` scope of `ALL` -
not merely "can edit the table", so a shared editor cannot silently repoint another
member's saved filter. Refused the same way every other per-resource write in this
package is: a 404, never a 403 that would disclose a row exists to a caller it
refuses.

Registers a `DependencyChecker` at import time: archiving a column a saved view
still filters, sorts or groups by is refused, naming the view, rather than leaving
the view silently broken (`app/services/virtual_tables/dependencies.py`).
"""

from contextlib import suppress
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, Perm, Scope
from app.db.models.table_view import TableView
from app.db.updates import writable
from app.repositories import table_view_repo
from app.schemas.table_view import (
    TableViewConfig,
    TableViewCreate,
    TableViewList,
    TableViewRead,
    TableViewUpdate,
    ViewKind,
    ViewVisibility,
)
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.dependencies import Dependent, register_dependency_checker


def _referenced_column_ids(config: dict[str, object]) -> set[UUID]:
    """Every column id a view's config names: its filters, its sort and its grouping."""
    ids: set[UUID] = set()
    visible = config.get("visible_columns")
    if isinstance(visible, list):
        ids.update(UUID(str(item)) for item in visible)
    group_by = config.get("group_by")
    if group_by:
        ids.add(UUID(str(group_by)))
    filters = config.get("filters")
    for item in filters if isinstance(filters, list) else []:
        column_id = item.get("column_id") if isinstance(item, dict) else None
        if column_id:
            ids.add(UUID(str(column_id)))
    sort = config.get("sort")
    sort_by = sort.get("by") if isinstance(sort, dict) else None
    if sort_by:
        # `created_at` / `updated_at` are not column ids, so a `ValueError` here just
        # means the sort names one of those rather than a column.
        with suppress(ValueError):
            ids.add(UUID(str(sort_by)))
    return ids


async def table_view_dependents(
    db: AsyncSession, *, organization_id: UUID, table_id: UUID, column_ids: frozenset[UUID] | None
) -> list[Dependent]:
    """Every saved view under this table whose config names one of `column_ids`.

    `column_ids=None` (the whole table is being archived) does not depend on any
    view - archiving a table does not touch its views, only removing a column a
    view still uses does.
    """
    if column_ids is None:
        return []
    views = await table_view_repo.list_views_for_table(
        db, organization_id=organization_id, table_id=table_id
    )
    return [
        Dependent(kind="table_view", id=view.id)
        for view in views
        if _referenced_column_ids(view.config) & column_ids
    ]


register_dependency_checker(table_view_dependents)


def _config_read(view: TableView) -> TableViewConfig:
    return TableViewConfig.model_validate(view.config)


def _read(view: TableView, *, can_manage: bool) -> TableViewRead:
    return TableViewRead(
        id=view.id,
        table_id=view.table_id,
        owner_user_id=view.owner_user_id,
        name=view.name,
        kind=cast(ViewKind, view.kind),
        visibility=cast(ViewVisibility, view.visibility),
        config=_config_read(view),
        can_manage=can_manage,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


class TableViewOperations(Operations):
    """List, create, read, update and delete the saved views of one table."""

    async def list_views(
        self, ctx: AuthContext, table_id: UUID, *, kind: str | None = None
    ) -> TableViewList:
        """The caller's own views plus the shared ones, under this table."""
        await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        views = await table_view_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table_id,
            user_id=ctx.subject_id,
            kind=kind,
        )
        items = [self._to_read(ctx, view) for view in views]
        return TableViewList(items=items, total=len(items))

    async def create_view(
        self, ctx: AuthContext, table_id: UUID, data: TableViewCreate
    ) -> TableViewRead:
        """Save a view. Creating one is a table-edit action, not a per-view one."""
        await self._load_table(ctx, table_id, Perm.TABLES_EDIT)
        if await table_view_repo.get_by_name(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table_id,
            owner_user_id=ctx.subject_id,
            name=data.name,
        ):
            raise AlreadyExistsError(
                message=f"A view named '{data.name}' already exists.", details={"name": data.name}
            )
        view = await table_view_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table_id,
            owner_user_id=ctx.subject_id,
            name=data.name,
            kind=data.kind,
            visibility=data.visibility,
            config=data.config.model_dump(mode="json"),
        )
        return self._to_read(ctx, view)

    async def get_view(self, ctx: AuthContext, table_id: UUID, view_id: UUID) -> TableViewRead:
        """One view, if the caller may see the table and either owns it or it is shared."""
        await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        view = await self._visible_view(ctx, table_id, view_id)
        return self._to_read(ctx, view)

    async def update_view(
        self, ctx: AuthContext, table_id: UUID, view_id: UUID, data: TableViewUpdate
    ) -> TableViewRead:
        """Rename, reconfigure or reshare a view.

        Refused to anyone but its owner or a caller whose `tables:edit` scope is
        `ALL` - a 404, the same as every other per-resource write in this package:
        whether a row may be changed is not disclosed to a caller it refuses.
        """
        await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        view = await self._manageable_view(ctx, table_id, view_id)
        # `config` excluded from `writable`: its column is JSONB, not a scalar, so it needs
        # `model_dump(mode="json")` on the nested model to keep a `UUID` from reaching asyncpg
        # unserialized, and `writable` does not offer a per-field dump mode.
        changes = writable(data, over=TableView, exclude={"config"})
        new_name = changes.get("name")
        if (
            new_name is not None
            and new_name != view.name
            and await table_view_repo.get_by_name(
                self.db,
                organization_id=ctx.organization_id,
                table_id=table_id,
                owner_user_id=view.owner_user_id,
                name=new_name,
            )
        ):
            raise AlreadyExistsError(
                message=f"A view named '{new_name}' already exists.",
                details={"name": new_name},
            )
        if data.config is not None:
            changes["config"] = data.config.model_dump(mode="json")
        if changes:
            view = await table_view_repo.update(self.db, view=view, update_data=changes)
        return self._to_read(ctx, view)

    async def delete_view(self, ctx: AuthContext, table_id: UUID, view_id: UUID) -> None:
        """Delete a view. Refused (404) to anyone but its owner or a caller with `tables:edit` `ALL`."""
        await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        view = await self._manageable_view(ctx, table_id, view_id)
        await table_view_repo.delete(self.db, view=view)

    async def _visible_view(self, ctx: AuthContext, table_id: UUID, view_id: UUID) -> TableView:
        view = await table_view_repo.get(
            self.db, organization_id=ctx.organization_id, view_id=view_id
        )
        # A private view owned by someone else is not merely refused, it does not exist for this
        # caller: whether it exists is itself something only its owner or a shared view discloses.
        if view is None or view.table_id != table_id or not self._visible_to(ctx, view):
            raise NotFoundError(message="View not found", details={"view_id": view_id})
        return view

    async def _manageable_view(self, ctx: AuthContext, table_id: UUID, view_id: UUID) -> TableView:
        """A view the caller may change or delete - its owner, or a `tables:edit` `ALL` scope.

        A view the caller may only *see* (shared, someone else's) answers the same 404 a
        private view does: every other per-resource write in this package refuses by hiding
        the row rather than by naming why, and a view is no exception.
        """
        view = await self._visible_view(ctx, table_id, view_id)
        if not self._can_manage(ctx, view):
            raise NotFoundError(message="View not found", details={"view_id": view_id})
        return view

    @staticmethod
    def _visible_to(ctx: AuthContext, view: TableView) -> bool:
        return view.visibility == "shared" or view.owner_user_id == ctx.subject_id

    @staticmethod
    def _can_manage(ctx: AuthContext, view: TableView) -> bool:
        return view.owner_user_id == ctx.subject_id or ctx.scope_for(Perm.TABLES_EDIT) is Scope.ALL

    def _to_read(self, ctx: AuthContext, view: TableView) -> TableViewRead:
        return _read(view, can_manage=self._can_manage(ctx, view))
