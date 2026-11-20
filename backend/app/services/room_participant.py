"""Manage explicit people and agent rosters for conversations."""

from collections.abc import Sequence
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.db.models.room_participant import RoomParticipant
from app.repositories import (
    agent as agent_repo,
)
from app.repositories import (
    conversation as conversation_repo,
)
from app.repositories import (
    conversation_task as conversation_task_repo,
)
from app.repositories import (
    member as member_repo,
)
from app.repositories import (
    room_participant as room_participant_repo,
)
from app.repositories import (
    room_submission as room_submission_repo,
)
from app.repositories import (
    user as user_repo,
)
from app.schemas.room_participant import (
    RoomCreate,
    RoomMentionableList,
    RoomMentionRead,
    RoomParticipantRead,
    RoomParticipantRef,
    RoomParticipantsRead,
)
from app.services.agent_registry import AgentRegistryService
from app.services.conversation import ConversationService

MAX_MENTIONABLE_AGENTS = 100
MAX_AUTOMATIC_AGENTS = 100


class RoomParticipantService:
    """Room creation, roster changes, and caller-scoped mention authorization."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationService(db)
        self.agents = AgentRegistryService(db)

    def _announce_participants_changed(self, conversation_id: UUID) -> None:
        """Refresh subscribed clients only after the roster transaction commits."""
        from app.core.background import spawn_after_commit
        from app.services.chat_room import room_participants

        spawn_after_commit(
            self.db,
            room_participants(str(conversation_id)),
            name="room-participants",
        )

    async def _read_preview(self, conversation: Conversation) -> list[RoomParticipant]:
        """Preview legacy personal-chat seed members without persisting access."""
        if conversation.room_visibility is not None or conversation.project_id is not None:
            return []
        return await self._preview_rows(conversation)

    async def _project_people(
        self, ctx: AuthContext, conversation: Conversation
    ) -> list[RoomParticipantRead]:
        """Project-view members are the human audience without duplicate room grants."""
        if conversation.project_id is None:
            return []
        actor_can_post = await self._can_post(ctx, conversation)
        people: list[RoomParticipantRead] = []
        for user in await room_participant_repo.active_people(
            self.db, organization_id=conversation.organization_id
        ):
            if not await self._target_can_view_project(conversation, target_user_id=user.id):
                continue
            people.append(
                RoomParticipantRead(
                    kind="user",
                    id=user.id,
                    name=user.full_name or user.email,
                    avatar_url=user.avatar_url,
                    is_member=True,
                    can_add=False,
                    can_mention=actor_can_post,
                    auto_reply=False,
                )
            )
        return people

    @staticmethod
    def _principal(ctx: AuthContext) -> tuple[UUID, UUID]:
        """Require a signed-in organization member for room operations."""
        if (
            ctx.user_id is None
            or ctx.organization_id is None
            or ctx.api_key_id is not None
            or ctx.is_impersonated
        ):
            raise AuthorizationError(
                message="A signed-in organization member is required for room access"
            )
        return ctx.organization_id, ctx.user_id

    async def _conversation(self, ctx: AuthContext, conversation_id: UUID) -> Conversation:
        organization_id, user_id = self._principal(ctx)
        if (
            await member_repo.get_active(self.db, organization_id=organization_id, user_id=user_id)
            is None
        ):
            raise AuthorizationError(message="An active organization member is required")
        return await self.conversations.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            ctx=ctx,
            include_messages=False,
            include_favourite=False,
        )

    async def _can_manage(self, ctx: AuthContext, conversation: Conversation) -> bool:
        _, user_id = self._principal(ctx)
        if await self.conversations._may_write(conversation, user_id, ctx=ctx):
            return True
        return conversation.project_id is not None and await self.conversations._project_allows(
            conversation, user_id, ctx, Perm.PROJECTS_EDIT
        )

    async def _can_post(self, ctx: AuthContext, conversation: Conversation) -> bool:
        _, user_id = self._principal(ctx)
        if conversation.project_id is not None:
            return await self.conversations._may_write(conversation, user_id, turn=True, ctx=ctx)
        if conversation.room_visibility is None:
            return await self.conversations._may_write(conversation, user_id, turn=True, ctx=ctx)
        is_member = await room_participant_repo.has_member(
            self.db,
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            user_id=user_id,
        )
        if is_member:
            return True
        if conversation.room_visibility == "public":
            return False
        # A pre-existing edit share retains its independent write grant. It does
        # not become a mention target or a roster entry unless explicitly added.
        return await self.conversations._may_write(conversation, user_id, turn=True, ctx=ctx)

    async def _target_can_view_project(
        self, conversation: Conversation, *, target_user_id: UUID
    ) -> bool:
        if conversation.project_id is None:
            return True
        member = await member_repo.get_active(
            self.db,
            organization_id=conversation.organization_id,
            user_id=target_user_id,
        )
        if member is None:
            return False
        target = AuthContext(
            user_id=target_user_id,
            organization_id=conversation.organization_id,
            role=member.role,
        )
        return await self.conversations._project_allows(
            conversation, target_user_id, target, Perm.PROJECTS_VIEW
        )

    async def _load_cloud_agent(
        self, ctx: AuthContext, agent_id: UUID
    ) -> tuple[Agent, AgentSpec, UUID]:
        """Resolve the current runnable version and enforce the room worker's surface."""
        agent, spec, version_id = await self.agents.get_runnable_spec(ctx, agent_id)
        # Import lazily: room submission uses this service at admission time.
        from app.services.room_submission import cloud_agent

        cloud_agent(spec)
        return agent, spec, version_id

    async def _is_cloud_runnable(self, ctx: AuthContext, agent_id: UUID) -> bool:
        try:
            await self._load_cloud_agent(ctx, agent_id)
        except AuthorizationError, BadRequestError, NotFoundError:
            return False
        return True

    async def _seed_roster(self, conversation: Conversation) -> bool:
        """Seed a converted chat with its owner and agents already in its history."""
        organization_id = conversation.organization_id
        changed = False
        if conversation.user_id is not None and await member_repo.get_active(
            self.db, organization_id=organization_id, user_id=conversation.user_id
        ):
            _, created = await room_participant_repo.add(
                self.db,
                organization_id=organization_id,
                conversation_id=conversation.id,
                user_id=conversation.user_id,
            )
            changed = changed or created
        agents = await conversation_repo.agents_in_conversations(self.db, [conversation.id])
        for agent in agents.get(conversation.id, []):
            _, created = await room_participant_repo.add(
                self.db,
                organization_id=organization_id,
                conversation_id=conversation.id,
                agent_id=agent.id,
            )
            changed = changed or created
        return changed

    async def _ensure_room_locked(self, conversation: Conversation) -> bool:
        """Convert a personal chat in place; project rooms keep their ACL metadata."""
        if conversation.origin == "workflow":
            raise NotFoundError(message="Conversation not found")
        if conversation.project_id is None and conversation.user_id is None:
            raise BadRequestError(
                message="Only a personal conversation can be converted to a private room"
            )
        # A project conversation stays under its project ACL and gets only the
        # agents explicitly added. A personal chat seeds history once, on the
        # transition from legacy to private; later changes must not resurrect a
        # participant somebody deliberately removed.
        if conversation.project_id is not None or conversation.room_visibility is not None:
            return False
        if (
            await conversation_repo.has_unfinished_runs(self.db, conversation.id)
            or await conversation_task_repo.has_live_conversation_work(self.db, conversation.id)
            or await room_submission_repo.active_count(self.db, conversation_id=conversation.id)
        ):
            raise ConflictError(
                message="Wait for this conversation's current work to finish before converting it"
            )
        conversation.room_visibility = "private"
        self.db.add(conversation)
        await self.db.flush()
        await self._seed_roster(conversation)
        return True

    async def ensure_room(self, ctx: AuthContext, conversation_id: UUID) -> Conversation:
        """Convert an authorized personal chat, preserving history and prior agents."""
        conversation = await self._conversation(ctx, conversation_id)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation.id)
        conversation = await self._conversation(ctx, conversation_id)
        if not await self._can_manage(ctx, conversation):
            raise AuthorizationError(message="Only a room manager may convert this conversation")
        if await self._ensure_room_locked(conversation):
            self._announce_participants_changed(conversation.id)
        return conversation

    async def _notify_added_user(
        self, ctx: AuthContext, conversation: Conversation, recipient: UUID
    ) -> None:
        _, actor_id = self._principal(ctx)
        if recipient == actor_id:
            return
        actor = await user_repo.get_by_id(self.db, actor_id)
        from app.services.notifications import NotificationService

        await NotificationService(self.db).conversation_shared(
            recipient=recipient,
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            title=conversation.title,
            sharer=(actor.full_name or actor.email) if actor is not None else "Someone",
            actor_user_id=actor_id,
        )

    async def _add_locked(
        self,
        ctx: AuthContext,
        conversation: Conversation,
        participant: RoomParticipantRef,
        *,
        can_manage: bool,
        actor_can_post: bool,
    ) -> RoomParticipant:
        organization_id, actor_id = self._principal(ctx)
        if participant.kind == "user":
            if conversation.project_id is not None:
                raise BadRequestError(
                    message="Project chat participants are managed by project access"
                )
            if not can_manage:
                raise AuthorizationError(message="Only a room manager may add people")
            member = await member_repo.get_active(
                self.db, organization_id=organization_id, user_id=participant.id
            )
            if member is None or not await self._target_can_view_project(
                conversation, target_user_id=participant.id
            ):
                raise NotFoundError(message="User not found")
            converted = await self._ensure_room_locked(conversation)
            row, created = await room_participant_repo.add(
                self.db,
                organization_id=organization_id,
                conversation_id=conversation.id,
                user_id=participant.id,
            )
            if created:
                await self._notify_added_user(ctx, conversation, participant.id)
            if created or converted:
                self._announce_participants_changed(conversation.id)
            return row

        actor_is_member = await room_participant_repo.has_member(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            user_id=actor_id,
        )
        if not can_manage and not (actor_is_member or (conversation.project_id and actor_can_post)):
            raise AuthorizationError(message="Join the room before adding an agent")
        await self._load_cloud_agent(ctx, participant.id)
        converted = await self._ensure_room_locked(conversation)
        row, created = await room_participant_repo.add(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            agent_id=participant.id,
        )
        if created or converted:
            self._announce_participants_changed(conversation.id)
        return row

    async def create_room(self, ctx: AuthContext, data: RoomCreate) -> Conversation:
        """Create a private or public room and add its initial roster."""
        organization_id, user_id = self._principal(ctx)
        if (
            await member_repo.get_active(self.db, organization_id=organization_id, user_id=user_id)
            is None
        ):
            raise AuthorizationError(message="An active organization member is required")
        conversation = await conversation_repo.create_conversation(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            title=data.title,
        )
        conversation.room_visibility = data.visibility
        self.db.add(conversation)
        await self.db.flush()
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation.id)
        await room_participant_repo.add(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            user_id=user_id,
        )
        seen: set[tuple[str, UUID]] = {("user", user_id)}
        for participant in data.participants:
            key = (participant.kind, participant.id)
            if key in seen:
                continue
            seen.add(key)
            await self._add_locked(
                ctx,
                conversation,
                participant,
                can_manage=True,
                actor_can_post=True,
            )
        # The room_visibility write advanced updated_at server-side; reload it so the
        # response can be serialized without further IO.
        await self.db.refresh(conversation)
        return await self.conversations.get_metadata(
            conversation.id,
            organization_id=organization_id,
            user_id=user_id,
            ctx=ctx,
        )

    async def add(
        self, ctx: AuthContext, conversation_id: UUID, participant: RoomParticipantRef
    ) -> RoomParticipantRead:
        """Add a person as a manager or a runnable agent as a room participant."""
        organization_id, _ = self._principal(ctx)
        conversation = await self._conversation(ctx, conversation_id)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation.id)
        conversation = await self._conversation(ctx, conversation_id)
        can_manage = await self._can_manage(ctx, conversation)
        actor_can_post = await self._can_post(ctx, conversation)
        row = await self._add_locked(
            ctx,
            conversation,
            participant,
            can_manage=can_manage,
            actor_can_post=actor_can_post,
        )
        return (await self._participant_reads(ctx, conversation, [row], stored=True))[0]

    async def remove(
        self, ctx: AuthContext, conversation_id: UUID, participant: RoomParticipantRef
    ) -> None:
        """Remove a room participant without changing the independent share or project ACL."""
        organization_id, _ = self._principal(ctx)
        conversation = await self._conversation(ctx, conversation_id)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation.id)
        conversation = await self._conversation(ctx, conversation_id)
        if not await self._can_manage(ctx, conversation):
            raise AuthorizationError(message="Only a room manager may remove participants")
        if participant.kind == "user" and participant.id == conversation.user_id:
            raise BadRequestError(message="The conversation owner cannot be removed")
        removed = await room_participant_repo.remove(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            user_id=participant.id if participant.kind == "user" else None,
            agent_id=participant.id if participant.kind == "agent" else None,
        )
        if not removed:
            raise NotFoundError(message="Room participant not found")
        self._announce_participants_changed(conversation.id)

    async def set_auto_reply(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        agent_id: UUID,
        *,
        auto_reply: bool,
    ) -> RoomParticipantRead:
        """Change a room agent's automatic-response preference as its manager."""
        organization_id, _ = self._principal(ctx)
        conversation = await self._conversation(ctx, conversation_id)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation.id)
        conversation = await self._conversation(ctx, conversation_id)
        if not await self._can_manage(ctx, conversation):
            raise AuthorizationError(message="Only a room manager may change agent settings")
        rows = await room_participant_repo.list_for_conversation(
            self.db, organization_id=organization_id, conversation_id=conversation.id
        )
        row = next((item for item in rows if item.agent_id == agent_id), None)
        if row is None:
            raise NotFoundError(message="Room agent not found")
        if row.auto_reply != auto_reply:
            await room_participant_repo.set_auto_reply(
                self.db,
                organization_id=organization_id,
                conversation_id=conversation.id,
                agent_id=agent_id,
                auto_reply=auto_reply,
            )
            row.auto_reply = auto_reply
            self._announce_participants_changed(conversation.id)
        return (await self._participant_reads(ctx, conversation, [row], stored=True))[0]

    async def _preview_rows(self, conversation: Conversation) -> list[RoomParticipant]:
        """A read-only preview of the owner and answerers seeded on first conversion."""
        organization_id = conversation.organization_id
        preview: list[RoomParticipant] = []
        if conversation.user_id is not None and await member_repo.get_active(
            self.db, organization_id=organization_id, user_id=conversation.user_id
        ):
            preview.append(
                RoomParticipant(
                    organization_id=organization_id,
                    conversation_id=conversation.id,
                    user_id=conversation.user_id,
                    agent_id=None,
                    auto_reply=False,
                )
            )
        agents = await conversation_repo.agents_in_conversations(self.db, [conversation.id])
        preview.extend(
            RoomParticipant(
                organization_id=organization_id,
                conversation_id=conversation.id,
                user_id=None,
                agent_id=agent.id,
                auto_reply=False,
            )
            for agent in agents.get(conversation.id, [])
        )
        return preview

    async def _participant_reads(
        self,
        ctx: AuthContext,
        conversation: Conversation,
        rows: Sequence[RoomParticipant],
        *,
        stored: bool,
        can_manage: bool | None = None,
        actor_can_post: bool | None = None,
    ) -> list[RoomParticipantRead]:
        organization_id, _ = self._principal(ctx)
        can_manage = await self._can_manage(ctx, conversation) if can_manage is None else can_manage
        actor_can_post = (
            await self._can_post(ctx, conversation) if actor_can_post is None else actor_can_post
        )
        users = await conversation_repo.users_by_id(
            self.db, {row.user_id for row in rows if row.user_id is not None}
        )
        agents = await agent_repo.get_many(
            self.db,
            [row.agent_id for row in rows if row.agent_id is not None],
            organization_id=organization_id,
        )
        reads: list[RoomParticipantRead] = []
        for row in rows:
            if row.user_id is not None:
                user = users.get(row.user_id)
                if user is None:
                    continue
                in_org = await member_repo.get_active(
                    self.db, organization_id=organization_id, user_id=user.id
                )
                project_access = in_org is not None and await self._target_can_view_project(
                    conversation, target_user_id=user.id
                )
                reads.append(
                    RoomParticipantRead(
                        kind="user",
                        id=user.id,
                        name=user.full_name or user.email,
                        avatar_url=user.avatar_url,
                        is_member=stored or conversation.project_id is not None,
                        can_add=False,
                        can_mention=(stored or conversation.project_id is not None)
                        and project_access
                        and actor_can_post,
                        auto_reply=False,
                    )
                )
                continue
            agent = agents.get(row.agent_id)
            if agent is None:
                continue
            callable_agent = await self._is_cloud_runnable(ctx, agent.id)
            reads.append(
                RoomParticipantRead(
                    kind="agent",
                    id=agent.id,
                    name=agent.name,
                    avatar_url=(
                        f"/api/v1/agents/{agent.id}/avatar"
                        if agent.avatar_url is not None
                        else None
                    ),
                    is_member=stored,
                    can_add=not stored and (can_manage or actor_can_post) and callable_agent,
                    can_mention=stored and callable_agent and actor_can_post,
                    auto_reply=row.auto_reply,
                )
            )
        return reads

    async def participants(self, ctx: AuthContext, conversation_id: UUID) -> RoomParticipantsRead:
        """Read the current roster; legacy personal chats get a read-only seed preview."""
        conversation = await self._conversation(ctx, conversation_id)
        organization_id, _ = self._principal(ctx)
        rows = await room_participant_repo.list_for_conversation(
            self.db, organization_id=organization_id, conversation_id=conversation_id
        )
        stored = bool(rows)
        if not rows:
            rows = await self._read_preview(conversation)
        can_manage = await self._can_manage(ctx, conversation)
        can_post = await self._can_post(ctx, conversation)
        items = await self._participant_reads(
            ctx,
            conversation,
            rows,
            stored=stored,
            can_manage=can_manage,
            actor_can_post=can_post,
        )
        if conversation.project_id is not None:
            project_people = await self._project_people(ctx, conversation)
            project_keys = {(item.kind, item.id) for item in project_people}
            items = project_people + [
                item for item in items if (item.kind, item.id) not in project_keys
            ]
        return RoomParticipantsRead(
            conversation_id=conversation.id,
            visibility=cast(Literal["private", "public"] | None, conversation.room_visibility),
            can_post=can_post,
            can_manage=can_manage,
            items=items,
        )

    async def mentionables(self, ctx: AuthContext, conversation_id: UUID) -> RoomMentionableList:
        """List current members first, then eligible people and cloud-runnable agents."""
        conversation = await self._conversation(ctx, conversation_id)
        organization_id, _ = self._principal(ctx)
        can_manage = await self._can_manage(ctx, conversation)
        actor_can_post = await self._can_post(ctx, conversation)
        rows = await room_participant_repo.list_for_conversation(
            self.db, organization_id=organization_id, conversation_id=conversation.id
        )
        stored = bool(rows)
        if not rows:
            rows = await self._read_preview(conversation)
        members = await self._participant_reads(
            ctx,
            conversation,
            rows,
            stored=stored,
            can_manage=can_manage,
            actor_can_post=actor_can_post,
        )
        items = list(members)
        seen = {(item.kind, item.id) for item in items}
        project_people = await self._project_people(ctx, conversation)
        project_keys = {(item.kind, item.id) for item in project_people}
        items = project_people + [
            item for item in items if (item.kind, item.id) not in project_keys
        ]
        seen.update((item.kind, item.id) for item in project_people)
        for user in await room_participant_repo.active_people(
            self.db, organization_id=organization_id
        ):
            key = ("user", user.id)
            if (
                conversation.project_id is not None
                or not can_manage
                or key in seen
                or not await self._target_can_view_project(conversation, target_user_id=user.id)
            ):
                continue
            items.append(
                RoomParticipantRead(
                    kind="user",
                    id=user.id,
                    name=user.full_name or user.email,
                    avatar_url=user.avatar_url,
                    is_member=False,
                    can_add=can_manage,
                    can_mention=False,
                    auto_reply=False,
                )
            )
            seen.add(key)

        visible, _ = await self.agents.list_agents(ctx, limit=MAX_MENTIONABLE_AGENTS)
        agent_ids = [item.id for item in visible]
        candidate_agents = await agent_repo.get_many(
            self.db, agent_ids, organization_id=organization_id
        )
        for candidate in visible:
            key = ("agent", candidate.id)
            if key in seen or not await self._is_cloud_runnable(ctx, candidate.id):
                continue
            agent = candidate_agents.get(candidate.id)
            if agent is None:
                continue
            items.append(
                RoomParticipantRead(
                    kind="agent",
                    id=agent.id,
                    name=agent.name,
                    avatar_url=(
                        f"/api/v1/agents/{agent.id}/avatar"
                        if agent.avatar_url is not None
                        else None
                    ),
                    is_member=False,
                    can_add=can_manage or actor_can_post,
                    can_mention=False,
                    auto_reply=False,
                )
            )
            seen.add(key)
        return RoomMentionableList(items=items)

    async def validate_mentions(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        participants: Sequence[RoomParticipantRef],
    ) -> list[RoomParticipantRead]:
        """Resolve only current roster members the caller may mention and run."""
        conversation = await self._conversation(ctx, conversation_id)
        organization_id, _ = self._principal(ctx)
        if not await self._can_post(ctx, conversation):
            raise AuthorizationError(message="Join the room before mentioning participants")
        if conversation.room_visibility is None and conversation.project_id is None:
            raise BadRequestError(message="Convert this conversation to a room before mentioning")
        result: list[RoomParticipantRead] = []
        seen: set[tuple[str, UUID]] = set()
        for participant in participants:
            key = (participant.kind, participant.id)
            if key in seen:
                continue
            seen.add(key)
            if participant.kind == "user":
                is_project_member = (
                    conversation.project_id is not None
                    and await self._target_can_view_project(
                        conversation, target_user_id=participant.id
                    )
                )
                is_roster_member = await room_participant_repo.has_member(
                    self.db,
                    organization_id=organization_id,
                    conversation_id=conversation.id,
                    user_id=participant.id,
                )
                if conversation.project_id is None and not is_roster_member:
                    raise AuthorizationError(message="Mentioned person is not a room member")
                user = await user_repo.get_by_id(self.db, participant.id)
                if (
                    user is None
                    or not user.is_active
                    or await member_repo.get_active(
                        self.db, organization_id=organization_id, user_id=participant.id
                    )
                    is None
                    or not await self._target_can_view_project(
                        conversation, target_user_id=participant.id
                    )
                    or (conversation.project_id is not None and not is_project_member)
                ):
                    raise AuthorizationError(message="Mentioned person no longer has room access")
                result.append(
                    RoomParticipantRead(
                        kind="user",
                        id=user.id,
                        name=user.full_name or user.email,
                        avatar_url=user.avatar_url,
                        is_member=True,
                        can_mention=True,
                    )
                )
                continue
            row = await room_participant_repo.get_agent(
                self.db,
                organization_id=organization_id,
                conversation_id=conversation.id,
                agent_id=participant.id,
            )
            if row is None:
                raise AuthorizationError(message="Mentioned agent is not a room member")
            agent, _, _ = await self._load_cloud_agent(ctx, participant.id)
            result.append(
                RoomParticipantRead(
                    kind="agent",
                    id=agent.id,
                    name=agent.name,
                    avatar_url=(
                        f"/api/v1/agents/{agent.id}/avatar"
                        if agent.avatar_url is not None
                        else None
                    ),
                    is_member=True,
                    can_mention=True,
                    auto_reply=row.auto_reply,
                )
            )
        return result

    async def automatic_agents(
        self, ctx: AuthContext, conversation_id: UUID
    ) -> list[RoomParticipantRead]:
        """Current runnable cloud agents explicitly opted into automatic replies."""
        conversation = await self._conversation(ctx, conversation_id)
        organization_id, _ = self._principal(ctx)
        rows = await room_participant_repo.list_for_conversation(
            self.db, organization_id=organization_id, conversation_id=conversation.id
        )
        selected: list[RoomParticipant] = []
        for row in rows:
            if row.agent_id is None or not row.auto_reply:
                continue
            if await self._is_cloud_runnable(ctx, row.agent_id):
                selected.append(row)
                if len(selected) == MAX_AUTOMATIC_AGENTS:
                    break
        return await self._participant_reads(ctx, conversation, selected, stored=True)

    async def list_public_rooms(
        self, ctx: AuthContext, *, skip: int, limit: int
    ) -> tuple[list[Conversation], int]:
        """Public rooms discoverable by an active organization member."""
        organization_id, user_id = self._principal(ctx)
        if (
            await member_repo.get_active(self.db, organization_id=organization_id, user_id=user_id)
            is None
        ):
            raise AuthorizationError(message="An active organization member is required")
        from app.services.room_thread_context_access import RoomThreadContextAccessService

        blocked = await RoomThreadContextAccessService(self.db).unreadable_destinations(
            organization_id=organization_id, user_id=user_id, actor=ctx
        )
        return await room_participant_repo.public_directory(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            skip=skip,
            limit=limit,
            excluded_conversation_ids=blocked,
        )

    async def join_public_room(self, ctx: AuthContext, conversation_id: UUID) -> Conversation:
        """Join a discoverable public room; the operation is safe to retry."""
        organization_id, user_id = self._principal(ctx)
        conversation = await self._conversation(ctx, conversation_id)
        if conversation.room_visibility != "public" or conversation.project_id is not None:
            raise NotFoundError(message="Public room not found")
        if (
            await member_repo.get_active(self.db, organization_id=organization_id, user_id=user_id)
            is None
        ):
            raise AuthorizationError(message="An active organization member is required")
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation.id)
        conversation = await self._conversation(ctx, conversation_id)
        if conversation.room_visibility != "public" or conversation.project_id is not None:
            raise NotFoundError(message="Public room not found")
        _, created = await room_participant_repo.add(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            user_id=user_id,
        )
        if created:
            self._announce_participants_changed(conversation.id)
        return await self.conversations.get_metadata(
            conversation.id,
            organization_id=organization_id,
            user_id=user_id,
            ctx=ctx,
        )


def mention_reads(items: Sequence[RoomParticipantRead]) -> list[RoomMentionRead]:
    """Narrow validated roster members to the canonical persisted mention shape."""
    return [
        RoomMentionRead(kind=item.kind, id=item.id, name=item.name)
        for item in items
        if item.can_mention
    ]
