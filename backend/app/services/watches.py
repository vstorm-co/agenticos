"""A person's watches over their own connections: set up, changed, read back (#2301).

Every rule an organization sets is checked here when a watch is written - that
watches are on, which servers may be read, how often at most - and again by the
sweep before each look, since the organization may change its mind after.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization
from app.db.models.watch import Watch
from app.db.updates import writable
from app.repositories import mcp_connection_repo, organization_repo, suggestion_repo, watch_repo
from app.schemas.watch import WatchCreate, WatchRead, WatchStopped, WatchUpdate
from app.services import watch_presets

MAX_WATCHES = 20
"""Per person and organization: each is a model call per look on their limit."""


def stopped_by(organization: Organization, connection: McpConnection) -> WatchStopped | None:
    """Why the organization's rules or the connection keep a watch from being read, if they do."""
    if not organization.proactive_watches_enabled:
        return "watches_off"
    if not connection.is_enabled:
        return "connection_disabled"
    return None


def watch_read(
    watch: Watch, *, organization: Organization, connection: McpConnection, waiting: int = 0
) -> WatchRead:
    return WatchRead(
        id=watch.id,
        connection_id=watch.connection_id,
        connection_name=connection.label or connection.name,
        server=connection.catalog_key,
        preset_key=watch.preset_key,
        title=watch.title,
        instructions=watch.instructions,
        exclusions=list(watch.exclusions),
        urgent=watch.urgent,
        interval_minutes=watch.interval_minutes,
        is_active=watch.is_active,
        stopped=stopped_by(organization, connection),
        next_run_at=watch.next_run_at,
        last_run_at=watch.last_run_at,
        waiting=waiting,
        created_at=watch.created_at,
    )


class WatchService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _person(ctx: AuthContext) -> UUID:
        if ctx.user_id is None:
            raise AuthenticationError(message="A watch belongs to a signed-in person")
        return ctx.user_id

    async def _organization(self, ctx: AuthContext) -> Organization:
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is None:
            raise NotFoundError(
                message="Organization not found",
                details={"organization_id": ctx.organization_id},
            )
        return organization

    async def _own_connection(self, person: UUID, connection_id: UUID) -> McpConnection:
        connection = await mcp_connection_repo.get_by_id(self.db, connection_id)
        if (
            connection is None
            or connection.scope != "user"
            or connection.purpose != "mcp"
            or connection.user_id != person
        ):
            raise refused_field("connection_id", "That is not one of your connections")
        return connection

    @staticmethod
    def _often_enough(organization: Organization, interval_minutes: int) -> None:
        floor = organization.proactive_watch_min_minutes
        if interval_minutes < floor:
            raise refused_field(
                "interval_minutes",
                f"Your organization allows a watch at most every {floor} minutes",
            )

    async def list_mine(self, ctx: AuthContext) -> list[WatchRead]:
        person = self._person(ctx)
        organization = await self._organization(ctx)
        watches = await watch_repo.list_own(
            self.db, organization_id=ctx.organization_id, user_id=person
        )
        waiting = await suggestion_repo.open_findings_by_watch(
            self.db, watch_ids=[watch.id for watch in watches]
        )
        reads: list[WatchRead] = []
        for watch in watches:
            connection = await mcp_connection_repo.get_by_id(self.db, watch.connection_id)
            if connection is not None:
                reads.append(
                    watch_read(
                        watch,
                        organization=organization,
                        connection=connection,
                        waiting=waiting.get(watch.id, 0),
                    )
                )
        return reads

    async def create(self, ctx: AuthContext, data: WatchCreate) -> WatchRead:
        """Set up a watch, first read within a minute.

        Raises:
            BadRequestError: Where the organization has watches off, the cadence
                is more often than it allows, the
                preset is for another server, or the person already has
                `MAX_WATCHES` - each naming the field it is about.
        """
        person = self._person(ctx)
        organization = await self._organization(ctx)
        connection = await self._own_connection(person, data.connection_id)
        stopped = stopped_by(organization, connection)
        if stopped == "watches_off":
            raise BadRequestError(message="Your organization has not turned watches on")
        self._often_enough(organization, data.interval_minutes)
        if data.preset_key is not None:
            preset = watch_presets.BY_KEY.get(data.preset_key)
            if preset is None or preset.catalog_key != connection.catalog_key:
                raise refused_field("preset_key", "That preset is not for this server")
        mine = await watch_repo.list_own(
            self.db, organization_id=ctx.organization_id, user_id=person
        )
        if len(mine) >= MAX_WATCHES:
            raise BadRequestError(
                message=f"You can have at most {MAX_WATCHES} watches",
                details={"limit": MAX_WATCHES},
            )
        watch = await watch_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            user_id=person,
            connection_id=connection.id,
            preset_key=data.preset_key,
            title=data.title,
            instructions=data.instructions,
            urgent=data.urgent,
            interval_minutes=data.interval_minutes,
            next_run_at=datetime.now(UTC),
        )
        return watch_read(watch, organization=organization, connection=connection)

    async def update(self, ctx: AuthContext, watch_id: UUID, data: WatchUpdate) -> WatchRead:
        person = self._person(ctx)
        organization = await self._organization(ctx)
        watch = await self._own(ctx, person, watch_id)
        changes = writable(data, over=Watch)
        if "interval_minutes" in changes:
            self._often_enough(organization, changes["interval_minutes"])
        if changes.get("is_active") is True and not watch.is_active:
            # Switched back on: look soon rather than at a time set weeks ago.
            changes["next_run_at"] = datetime.now(UTC)
        watch = await watch_repo.update_fields(self.db, watch=watch, changes=changes)
        connection = await self._own_connection(person, watch.connection_id)
        return watch_read(watch, organization=organization, connection=connection)

    async def delete(self, ctx: AuthContext, watch_id: UUID) -> None:
        """Remove it, and what it found with it."""
        watch = await self._own(ctx, self._person(ctx), watch_id)
        await watch_repo.delete(self.db, watch)

    async def _own(self, ctx: AuthContext, person: UUID, watch_id: UUID) -> Watch:
        watch = await watch_repo.get_own(
            self.db, watch_id, organization_id=ctx.organization_id, user_id=person
        )
        if watch is None:
            raise NotFoundError(message="No such watch", details={"watch_id": watch_id})
        return watch

    @staticmethod
    def presets() -> list[watch_presets.WatchPreset]:
        return list(watch_presets.PRESETS)
