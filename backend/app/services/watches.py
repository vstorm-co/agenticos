"""A person's watches over their own connections: set up, changed, read back (#2301).

Every rule an organization sets is checked here when a watch is written - that
watches are on, which servers may be read, how often at most - and again by the
sweep before each look, since the organization may change its mind after.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.audit import current_impersonator
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization
from app.db.models.watch import Watch
from app.db.updates import writable
from app.repositories import (
    mcp_connection_repo,
    organization_repo,
    suggestion_repo,
    watch_repo,
)
from app.schemas.routine_notifications import read_channels, read_report_mode
from app.schemas.watch import WatchCreate, WatchRead, WatchStopped, WatchUpdate
from app.schemas.watch_sources import WatchSources
from app.services import watch_presets
from app.services.agent_registry import AgentRegistryService
from app.services.conversation import ConversationService
from app.services.outcome import OutcomeService
from app.services.primary_conversation import PrimaryConversationService
from app.services.watch_sources import approve_sources, constrain_sources

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
        notification_channels=read_channels(watch.notification_channels),
        report_mode=read_report_mode(watch.report_mode),
        id=watch.id,
        agent_id=watch.agent_id,
        environment_id=watch.environment_id,
        pinned_version_id=watch.pinned_version_id,
        ends_at=watch.ends_at,
        source_conversation_id=watch.source_conversation_id,
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
        stopped=stopped_by(organization, connection)
        or ("needs_agent" if watch.agent_id is None else None),
        next_run_at=watch.next_run_at,
        last_run_at=watch.last_run_at,
        last_attempt_at=watch.last_attempt_at,
        last_attempt_status=watch.last_attempt_status,
        max_failures=watch.max_failures,
        consecutive_failures=watch.consecutive_failures or 0,
        auto_stopped_at=watch.auto_stopped_at,
        waiting=waiting,
        created_at=watch.created_at,
    )


class WatchService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _selected_spec(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        environment_id: UUID | None,
        pinned_version_id: UUID | None,
    ) -> AgentSpec:
        if environment_id is not None and pinned_version_id is not None:
            raise refused_field(
                "pinned_version_id", "Choose an environment or a pinned version, not both"
            )
        registry = AgentRegistryService(self.db)
        if pinned_version_id is None:
            agent, spec, _ = await registry.get_runnable_spec(
                ctx, agent_id, environment_id=environment_id
            )
        else:
            agent, spec, _ = await registry.get_pinned_spec(ctx, agent_id, pinned_version_id)
        return await registry.with_assistant_guidance(agent, spec)

    @staticmethod
    def _end(ends_at: datetime | None) -> None:
        if ends_at is not None and ends_at <= datetime.now(UTC):
            raise refused_field("ends_at", "The end must be in the future")

    async def _source_conversation(self, ctx: AuthContext, agent_id: UUID) -> UUID:
        if ctx.source_conversation_id is not None:
            conversation = await ConversationService(self.db).get_conversation(
                ctx.source_conversation_id,
                organization_id=ctx.organization_id,
                user_id=ctx.user_id,
                for_write=True,
                turn=True,
                include_favourite=False,
                ctx=ctx,
            )
            if (
                conversation is None
                or conversation.organization_id != ctx.organization_id
                or conversation.user_id != ctx.user_id
            ):
                raise NotFoundError(message="Source conversation not found")
            return conversation.id
        return await PrimaryConversationService(self.db).ensure(
            organization_id=ctx.organization_id, user_id=ctx.subject_id, agent_id=agent_id
        )

    @staticmethod
    def _person(ctx: AuthContext) -> UUID:
        if ctx.user_id is None:
            raise AuthenticationError(message="A watch belongs to a signed-in person")
        return ctx.user_id

    @staticmethod
    def _require_personal_consent(ctx: AuthContext) -> None:
        """A background turn or an agent's credential cannot grant itself future reads of a private account.

        The person may: signed in, through a key or MCP token they issued, or in
        their own private chat.
        """
        if not ctx.acts_in_person or current_impersonator() is not None:
            raise AuthorizationError(
                message="Creating or changing a watch requires the person's own consent in a private conversation, signed-in session or their own API key."
            )

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
        self._require_personal_consent(ctx)
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
        self._end(data.ends_at)
        spec = await self._selected_spec(
            ctx,
            data.agent_id,
            environment_id=data.environment_id,
            pinned_version_id=data.pinned_version_id,
        )
        sources = approve_sources(spec, connection)
        source_conversation_id = await self._source_conversation(ctx, data.agent_id)
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
            max_failures=data.max_failures,
            notification_channels=data.notification_channels,
            report_mode=data.report_mode,
            agent_id=data.agent_id,
            environment_id=data.environment_id,
            pinned_version_id=data.pinned_version_id,
            approved_sources=sources.model_dump(mode="json"),
            source_conversation_id=source_conversation_id,
            ends_at=data.ends_at,
        )
        return watch_read(watch, organization=organization, connection=connection)

    async def update(self, ctx: AuthContext, watch_id: UUID, data: WatchUpdate) -> WatchRead:
        person = self._person(ctx)
        self._require_personal_consent(ctx)
        organization = await self._organization(ctx)
        watch = await self._own(ctx, person, watch_id, for_update=True)
        changes = writable(data, over=Watch, exclude={"review_sources"})
        if "max_failures" in changes or changes.get("is_active") is True:
            changes["health_reset_at"] = datetime.now(UTC)
            changes["consecutive_failures"] = 0
        if "is_active" in changes or "max_failures" in changes:
            changes["auto_stopped_at"] = None

        connection = await self._own_connection(person, watch.connection_id)
        agent_id = data.agent_id or watch.agent_id
        if agent_id is None and changes.get("is_active") is True:
            raise refused_field("agent_id", "Select the agent that will execute this watch")
        if "ends_at" in changes:
            self._end(data.ends_at)
        if data.agent_id is not None and data.agent_id != watch.agent_id:
            changes.setdefault("environment_id", None)
            changes.setdefault("pinned_version_id", None)
        if agent_id is not None and (
            {"agent_id", "environment_id", "pinned_version_id"}.intersection(data.model_fields_set)
            or data.review_sources
        ):
            spec = await self._selected_spec(
                ctx,
                agent_id,
                environment_id=changes.get("environment_id", watch.environment_id),
                pinned_version_id=changes.get("pinned_version_id", watch.pinned_version_id),
            )
            if agent_id != watch.agent_id or data.review_sources or watch.approved_sources is None:
                changes["approved_sources"] = approve_sources(spec, connection).model_dump(
                    mode="json"
                )
            else:
                constrain_sources(spec, WatchSources.model_validate(watch.approved_sources))
            if watch.agent_id is None:
                changes["source_conversation_id"] = await self._source_conversation(ctx, agent_id)
                changes["next_run_at"] = datetime.now(UTC)
        if "interval_minutes" in changes:
            self._often_enough(organization, changes["interval_minutes"])
        if changes.get("is_active") is True and not watch.is_active:
            # Switched back on: look soon rather than at a time set weeks ago.
            changes["next_run_at"] = datetime.now(UTC)
        watch = await watch_repo.update_fields(self.db, watch=watch, changes=changes)
        return watch_read(watch, organization=organization, connection=connection)

    async def delete(self, ctx: AuthContext, watch_id: UUID) -> None:
        """Remove it, and what it found with it."""
        self._require_personal_consent(ctx)
        watch = await self._own(ctx, self._person(ctx), watch_id, for_update=True)
        await OutcomeService(self.db).resolve_watch_findings(
            organization_id=ctx.organization_id, user_id=self._person(ctx), watch_id=watch.id
        )
        await OutcomeService(self.db).resolve_routine_attention(
            organization_id=watch.organization_id,
            user_id=watch.user_id,
            routine_id=watch.id,
            routine_kind="watch",
        )
        await watch_repo.delete(self.db, watch)

    async def _own(
        self, ctx: AuthContext, person: UUID, watch_id: UUID, *, for_update: bool = False
    ) -> Watch:
        watch = await watch_repo.get_own(
            self.db,
            watch_id,
            organization_id=ctx.organization_id,
            user_id=person,
            for_update=for_update,
        )
        if watch is None:
            raise NotFoundError(message="No such watch", details={"watch_id": watch_id})
        return watch

    @staticmethod
    def presets() -> list[watch_presets.WatchPreset]:
        return list(watch_presets.PRESETS)
