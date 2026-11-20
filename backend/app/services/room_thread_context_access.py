"""Audience checks for imported thread context between conversations."""

from collections import deque
from dataclasses import replace
from typing import NoReturn
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.conversation import Conversation
from app.repositories import room_thread_context_access as room_thread_context_access_repo

MAX_CONTEXT_SOURCE_NODES = 256
"""Maximum distinct conversations in one inherited context closure, including its root."""
MAX_CONTEXT_SOURCE_DEPTH = 32
"""Maximum number of external context edges in one shortest path."""


class RoomThreadContextAccessService:
    """Prove a referenced source range is visible to a destination's audience."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def can_read_sources(
        self,
        destination: Conversation,
        user_id: UUID,
        actor: AuthContext | None = None,
    ) -> bool:
        """Whether the user can read every external source inherited by a room.

        Only direct conversation ACLs are evaluated here. The iterative walk
        covers every transitive RoomThread source edge without recursively
        invoking the canonical conversation wrapper. Cycles are safe because a
        visited node is checked once, while a cycle back to the destination is
        still checked as a source.
        """
        organization_id = destination.organization_id
        if organization_id is None or not self._actor_matches(actor, organization_id, user_id):
            return False

        conversations: dict[UUID, Conversation] = {destination.id: destination}
        visited = {destination.id}
        frontier = {destination.id}
        direct_permissions: dict[UUID, bool] = {}
        depth = 0

        while frontier:
            edges = await room_thread_context_access_repo.external_context_edges(
                self.db,
                organization_id=organization_id,
                destination_ids=frontier,
            )
            source_ids = {source_id for _, source_id in edges}
            if not source_ids:
                return True

            new_ids = source_ids - visited
            if new_ids and depth >= MAX_CONTEXT_SOURCE_DEPTH:
                return False
            if len(visited | new_ids) > MAX_CONTEXT_SOURCE_NODES:
                return False

            missing = source_ids - conversations.keys()
            if missing:
                conversations.update(
                    await room_thread_context_access_repo.conversations_by_ids(
                        self.db,
                        organization_id=organization_id,
                        conversation_ids=missing,
                    )
                )

            for source_id in source_ids:
                source = conversations.get(source_id)
                if source is None or source.organization_id != organization_id:
                    return False
                if not await self._direct_readable(
                    source,
                    user_id,
                    actor=actor,
                    cache=direct_permissions,
                ):
                    return False

            visited.update(new_ids)
            frontier = new_ids
            depth += 1
        return True

    async def assert_responder_visible(
        self, *, destination: Conversation, responder_agent_id: UUID
    ) -> None:
        """Require the actual responder on every private source in the room's closure.

        A room can quote or summarize content imported by an earlier room. Checking
        only the immediate source lets a responder newly added to an intermediate
        room receive text whose original private source roster does not include it.
        This bounded walk checks each source once, fails closed on broken graph
        rows, and keeps the public standalone-room exception at every level.
        """
        organization_id = destination.organization_id
        if organization_id is None or not self._is_room_or_project(destination):
            self._refuse_responder()

        conversations: dict[UUID, Conversation] = {destination.id: destination}
        visited = {destination.id}
        frontier = {destination.id}
        rosters: dict[UUID, set[UUID]] = {}
        depth = 0

        while frontier:
            edges = await room_thread_context_access_repo.external_context_edges(
                self.db,
                organization_id=organization_id,
                destination_ids=frontier,
            )
            if any(edge_destination_id not in frontier for edge_destination_id, _ in edges):
                self._refuse_responder()
            source_ids = {source_id for _, source_id in edges}
            if not source_ids:
                return

            new_ids = source_ids - visited
            if new_ids and depth >= MAX_CONTEXT_SOURCE_DEPTH:
                self._refuse_responder()
            if len(visited | new_ids) > MAX_CONTEXT_SOURCE_NODES:
                self._refuse_responder()

            missing = source_ids - conversations.keys()
            if missing:
                conversations.update(
                    await room_thread_context_access_repo.conversations_by_ids(
                        self.db,
                        organization_id=organization_id,
                        conversation_ids=missing,
                    )
                )

            for source_id in sorted(source_ids, key=str):
                source = conversations.get(source_id)
                if (
                    source is None
                    or source.organization_id != organization_id
                    or not self._is_room_or_project(source)
                ):
                    self._refuse_responder()
                if self._is_public_room(source):
                    continue
                if source_id not in rosters:
                    rosters[source_id] = await room_thread_context_access_repo.agent_ids(
                        self.db,
                        organization_id=organization_id,
                        conversation_id=source_id,
                    )
                if responder_agent_id not in rosters[source_id]:
                    self._refuse_responder()

            visited.update(new_ids)
            frontier = new_ids
            depth += 1

    async def unreadable_destinations(
        self,
        organization_id: UUID,
        user_id: UUID,
        actor: AuthContext | None = None,
    ) -> set[UUID]:
        """Return rooms whose imported source closure this user cannot read.

        The graph and conversation rows are loaded once for a search/list pass;
        direct ACL results are cached across all destination roots.
        """
        if not self._actor_matches(actor, organization_id, user_id):
            edges: list[
                tuple[UUID, UUID]
            ] = await room_thread_context_access_repo.external_context_edges(
                self.db, organization_id=organization_id
            )
            return {destination_id for destination_id, _ in edges}

        edges = await room_thread_context_access_repo.external_context_edges(
            self.db, organization_id=organization_id
        )
        if not edges:
            return set()

        adjacency: dict[UUID, set[UUID]] = {}
        roots: set[UUID] = set()
        all_ids: set[UUID] = set()
        for destination_id, source_id in edges:
            adjacency.setdefault(destination_id, set()).add(source_id)
            roots.add(destination_id)
            all_ids.update((destination_id, source_id))

        conversations = await room_thread_context_access_repo.conversations_by_ids(
            self.db,
            organization_id=organization_id,
            conversation_ids=all_ids,
        )
        direct_permissions: dict[UUID, bool] = {}
        unreadable: set[UUID] = set()

        for root_id in roots:
            pending = deque([(root_id, 0)])
            visited: set[UUID] = set()
            source_ids: set[UUID] = set()
            invalid_closure = False

            while pending:
                conversation_id, depth = pending.popleft()
                if conversation_id in visited:
                    continue
                if len(visited) >= MAX_CONTEXT_SOURCE_NODES:
                    invalid_closure = True
                    break
                conversation = conversations.get(conversation_id)
                if conversation is None or conversation.organization_id != organization_id:
                    invalid_closure = True
                    break
                visited.add(conversation_id)

                children = adjacency.get(conversation_id, set())
                new_children = children - visited
                if new_children and depth >= MAX_CONTEXT_SOURCE_DEPTH:
                    invalid_closure = True
                    break
                if len(visited | new_children) > MAX_CONTEXT_SOURCE_NODES:
                    invalid_closure = True
                    break
                source_ids.update(children)
                pending.extend((source_id, depth + 1) for source_id in new_children)

            if invalid_closure:
                unreadable.add(root_id)
                continue

            for source_id in source_ids:
                source = conversations.get(source_id)
                if source is None or source.organization_id != organization_id:
                    unreadable.add(root_id)
                    break
                if not await self._direct_readable(
                    source,
                    user_id,
                    actor=actor,
                    cache=direct_permissions,
                ):
                    unreadable.add(root_id)
                    break

        return unreadable

    async def assert_visible(
        self,
        *,
        destination: Conversation,
        source: Conversation,
        actor: AuthContext | None = None,
        responder_agent_id: UUID | None = None,
    ) -> None:
        """Refuse cross-room context unless current human and agent audiences overlap safely."""
        organization_id = destination.organization_id
        if (
            organization_id is None
            or source.organization_id != organization_id
            or (actor is not None and actor.organization_id != organization_id)
        ):
            self._refuse(source, destination)

        # The route already authorizes an ordinary in-conversation thread. This
        # guard proves both records belong to the caller's tenant before allowing
        # that same-conversation case to bypass the cross-room audience checks.
        if destination.id == source.id:
            return

        if not self._is_room_or_project(destination) or not self._is_room_or_project(source):
            self._refuse(source, destination)

        # A bearer link has an unbounded, unidentifiable audience. A cross-room
        # reference cannot safely promise that audience is covered by the source.
        if await room_thread_context_access_repo.has_bearer_share(
            self.db, conversation_id=destination.id
        ):
            self._refuse(source, destination)

        members = await room_thread_context_access_repo.active_member_contexts(
            self.db, organization_id=organization_id
        )
        members_by_id = {member.user_id: member for member in members}

        if actor is not None:
            if actor.user_id is None:
                self._refuse(source, destination)
            actor_member = members_by_id.get(actor.user_id)
            if actor_member is None:
                self._refuse(source, destination)
            current_actor = replace(
                actor,
                role=actor_member.role,
                is_app_admin=actor_member.is_app_admin,
            )
            if not await self._may_read_direct(destination, actor.user_id, ctx=current_actor):
                self._refuse(source, destination)
            if not await self._may_read(source, actor.user_id, ctx=current_actor):
                self._refuse(source, destination)

        # Use the direct ACL for the destination's potential readers. Applying
        # inherited source policy to the destination here would recursively test
        # the whole audience of every source room.
        for member in members:
            context = AuthContext(
                user_id=member.user_id,
                organization_id=organization_id,
                role=member.role,
                is_app_admin=member.is_app_admin,
            )
            destination_visible = await self._may_read_direct(
                destination, member.user_id, ctx=context
            )
            source_visible = destination_visible and await self._may_read(
                source, member.user_id, ctx=context
            )
            if destination_visible and not source_visible:
                self._refuse(source, destination)

        # Public standalone rooms intentionally admit cross-room agent context.
        # For private rooms and project chats, retain the broad roster guarantee:
        # every configured destination agent must also belong to the source.
        if not self._is_public_room(source):
            source_agents = await room_thread_context_access_repo.agent_ids(
                self.db,
                organization_id=organization_id,
                conversation_id=source.id,
            )
            destination_agents = await room_thread_context_access_repo.agent_ids(
                self.db,
                organization_id=organization_id,
                conversation_id=destination.id,
            )
            if not destination_agents.issubset(source_agents):
                self._refuse(source, destination)
            # A project-room request can explicitly run a published agent that
            # is not on that room's roster. The submission, not the roster or
            # project default, identifies the actual model receiving this
            # context. Recheck that agent's current source membership at each
            # model-history boundary.
            if responder_agent_id is not None and responder_agent_id not in source_agents:
                self._refuse(source, destination)

    async def _may_read(
        self, conversation: Conversation, user_id: UUID, *, ctx: AuthContext
    ) -> bool:
        """Delegate inherited source authority to the canonical conversation policy."""
        # Lazy import avoids a module cycle when conversation services call this
        # helper at history and model-request boundaries.
        from app.services.conversation import ConversationService

        return await ConversationService(self.db)._may_read(conversation, user_id, ctx=ctx)

    async def _may_read_direct(
        self, conversation: Conversation, user_id: UUID, *, ctx: AuthContext | None
    ) -> bool:
        """Delegate one node's direct ACL without traversing its context edges."""
        from app.services.conversation import ConversationService

        return await ConversationService(self.db)._may_read_direct(conversation, user_id, ctx=ctx)

    async def _direct_readable(
        self,
        conversation: Conversation,
        user_id: UUID,
        *,
        actor: AuthContext | None,
        cache: dict[UUID, bool],
    ) -> bool:
        if conversation.id not in cache:
            cache[conversation.id] = await self._may_read_direct(
                conversation,
                user_id,
                ctx=actor,
            )
        return cache[conversation.id]

    @staticmethod
    def _actor_matches(actor: AuthContext | None, organization_id: UUID, user_id: UUID) -> bool:
        return actor is None or (
            actor.organization_id == organization_id and actor.user_id == user_id
        )

    @staticmethod
    def _is_room_or_project(conversation: Conversation) -> bool:
        return conversation.origin != "workflow" and (
            conversation.project_id is not None
            or conversation.room_visibility in {"private", "public"}
        )

    @staticmethod
    def _is_public_room(conversation: Conversation) -> bool:
        return conversation.project_id is None and conversation.room_visibility == "public"

    @staticmethod
    def _refuse(source: Conversation, destination: Conversation) -> NoReturn:
        raise AuthorizationError(
            message="Thread context is not available to this destination.",
            details={
                "source_conversation_id": str(source.id),
                "destination_conversation_id": str(destination.id),
            },
        )

    @staticmethod
    def _refuse_responder() -> NoReturn:
        raise AuthorizationError(message="Thread context is not available to this responder.")
