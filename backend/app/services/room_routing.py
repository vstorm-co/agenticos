"""Human-reviewed room proposals reuse the canonical task lifecycle and queue."""

import hashlib
import json
from contextlib import suppress
from uuid import UUID, uuid4, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.room_lead import RoomLeadPlanning
from app.core.exceptions import (
    AlreadyExistsError,
    AppException,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.conversation import Conversation
from app.db.models.room_routing import RoomLeadPolicy, RoomRoutingProposal, RoomTaskLink
from app.db.models.room_submission import RoomSubmission
from app.repositories import conversation as conversation_repo
from app.repositories import project_repo, user_repo, virtual_table_repo
from app.repositories import room_routing as routing_repo
from app.repositories import room_submission as room_repo
from app.repositories import task as task_repo
from app.schemas.room_routing import (
    RoomAgentPin,
    RoomAgentPinRead,
    RoomLeadPolicyRead,
    RoomLeadPolicyWrite,
    RoomProposalAccept,
    RoomProposalCreate,
    RoomProposalDiscard,
    RoomProposalItem,
    RoomProposalItemRead,
    RoomRoutingProposalList,
    RoomRoutingProposalRead,
    RoomTaskCard,
    RoomTaskCardList,
)
from app.schemas.task import TaskCreate, TaskRead
from app.services.access import PROJECT, acting_member, resolve_access
from app.services.agent_registry import AgentRegistryService
from app.services.room_submission import (
    RoomSubmissionService,
    announce_request,
    cloud_agent,
    signed_in,
)
from app.services.task_access import scope_allows
from app.services.tasks import TaskService


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _stored_item(value: dict[str, object]) -> RoomProposalItem:
    return RoomProposalItem.model_validate(
        {key: item for key, item in value.items() if key != "proposal_item_id"}
    )


class RoomRoutingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.rooms = RoomSubmissionService(db)
        self.tasks = TaskService(db)
        self.registry = AgentRegistryService(db)
        self._read_pins: dict[tuple[UUID | None, UUID, UUID], RoomAgentPinRead | None] = {}
        self._accountable_names: dict[tuple[UUID, UUID], str | None] = {}

    async def _accountable_name(
        self,
        ctx: AuthContext,
        user_id: UUID | None,
        project_id: UUID | None,
    ) -> str | None:
        if user_id is None or project_id is None:
            return None
        key = (user_id, project_id)
        if key not in self._accountable_names:
            member = await acting_member(self.db, ctx.organization_id, str(user_id))
            name = None
            if member is not None and await scope_allows(
                self.db, member, "project", project_id, edit=True
            ):
                person = await user_repo.get_by_id(self.db, user_id)
                if person is not None:
                    name = person.full_name
            self._accountable_names[key] = name
        return self._accountable_names[key]

    async def _editable(self, ctx: AuthContext, room: Conversation) -> bool:
        if room.project_id is None or room.is_archived:
            return False
        project = await project_repo.get(
            self.db, room.project_id, organization_id=ctx.organization_id
        )
        return project is not None and await resolve_access(
            self.db,
            ctx,
            project,
            Perm.PROJECTS_EDIT,
            resource_type=PROJECT,
        )

    async def _pin(
        self, ctx: AuthContext, agent_id: UUID, version_id: UUID | None = None
    ) -> RoomAgentPinRead:
        agent, spec, current = await self.registry.get_runnable_spec(ctx, agent_id)
        cloud_agent(spec)
        if version_id is not None:
            _, pinned, _ = await self.registry.get_pinned_spec(ctx, agent_id, version_id)
            cloud_agent(pinned)
        return RoomAgentPinRead(
            agent_id=agent.id,
            version_id=version_id or current,
            name=agent.name,
            current=version_id is None or version_id == current,
        )

    async def _read_pin(self, ctx: AuthContext, pin: RoomAgentPin) -> RoomAgentPinRead | None:
        key = (ctx.user_id, pin.agent_id, pin.version_id)
        if key not in self._read_pins:
            try:
                self._read_pins[key] = await self._pin(ctx, pin.agent_id, pin.version_id)
            except AppException:
                self._read_pins[key] = None
        return self._read_pins[key]

    async def policy(self, ctx: AuthContext, conversation_id: UUID) -> RoomLeadPolicyRead:
        signed_in(ctx)
        room = await self.rooms.room(ctx, conversation_id)
        row = await routing_repo.policy(self.db, ctx.organization_id, conversation_id)
        result = RoomLeadPolicyRead(can_edit=await self._editable(ctx, room))
        if row is None:
            return result
        result.enabled, result.revision, result.max_items = row.enabled, row.revision, row.max_items
        if row.lead_agent_id is not None and row.lead_version_id is not None:
            result.lead = await self._read_pin(
                ctx,
                RoomAgentPin(agent_id=row.lead_agent_id, version_id=row.lead_version_id),
            )
        for value in row.specialists:
            pin = await self._read_pin(ctx, RoomAgentPin.model_validate(value))
            if pin is not None:
                result.specialists.append(pin)
        if row.enabled and result.lead is not None:
            try:
                await self.rooms.room(ctx, conversation_id, for_write=True)
                result.can_ask = True
            except AppException:
                pass
        return result

    async def update_policy(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        data: RoomLeadPolicyWrite,
    ) -> RoomLeadPolicyRead:
        signed_in(ctx)
        room = await self.rooms.room(ctx, conversation_id, for_write=True)
        if not await self._editable(ctx, room):
            raise AuthorizationError(
                message="Editing room lead policy requires project edit access"
            )
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        row = await routing_repo.policy(self.db, ctx.organization_id, conversation_id)
        if data.expected_revision != (0 if row is None else row.revision):
            raise AlreadyExistsError(
                message="The room lead policy changed; review its current revision"
            )
        lead = await self._pin(ctx, data.lead_agent_id) if data.lead_agent_id is not None else None
        specialists = []
        for agent_id in data.specialist_agent_ids:
            pin = await self._pin(ctx, agent_id)
            specialists.append(
                RoomAgentPin(agent_id=pin.agent_id, version_id=pin.version_id).model_dump(
                    mode="json"
                )
            )
        if row is None:
            row = RoomLeadPolicy(
                organization_id=ctx.organization_id, conversation_id=conversation_id, revision=0
            )
        row.enabled, row.max_items = data.enabled, data.max_items
        row.lead_agent_id = None if lead is None else lead.agent_id
        row.lead_version_id = None if lead is None else lead.version_id
        row.specialists = specialists
        row.revision += 1
        await routing_repo.save(self.db, row)
        self._read_pins.clear()
        return await self.policy(ctx, conversation_id)

    async def active_policy(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        expected_revision: int,
    ) -> RoomLeadPolicy:
        row = await routing_repo.policy(self.db, ctx.organization_id, conversation_id)
        if (
            row is None
            or not row.enabled
            or row.revision != expected_revision
            or row.lead_agent_id is None
            or row.lead_version_id is None
        ):
            raise AlreadyExistsError(
                message="Room lead routing is disabled or its policy changed",
                code="ROOM_LEAD_POLICY_CHANGED",
            )
        return row

    async def admit(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        expected_revision: int,
    ) -> tuple[UUID, UUID]:
        row = await self.active_policy(ctx, conversation_id, expected_revision)
        lead_id, version_id = row.lead_agent_id, row.lead_version_id
        assert lead_id is not None and version_id is not None, "active policy has a pinned lead"
        pin = await self._pin(ctx, lead_id, version_id)
        return pin.agent_id, pin.version_id

    async def submission_policy(
        self, ctx: AuthContext, submission: RoomSubmission
    ) -> RoomLeadPolicy:
        if submission.intent != "ask_lead" or submission.lead_policy_revision is None:
            raise BadRequestError(message="This room request did not ask the lead")
        row = await self.active_policy(
            ctx, submission.conversation_id, submission.lead_policy_revision
        )
        if (row.lead_agent_id, row.lead_version_id) != (submission.agent_id, submission.version_id):
            raise AlreadyExistsError(message="The room lead policy changed")
        return row

    async def _thread(self, conversation_id: UUID, thread_root_message_id: UUID | None) -> None:
        if thread_root_message_id is None:
            return
        root = await conversation_repo.get_message_by_id(self.db, thread_root_message_id)
        if (
            root is None
            or root.conversation_id != conversation_id
            or root.thread_root_message_id is not None
        ):
            raise NotFoundError(message="Room thread not found")

    async def _existing(
        self,
        ctx: AuthContext,
        room: Conversation,
        item: RoomProposalItem,
        *,
        lock: bool = False,
    ) -> TaskRead | None:
        if item.existing_task_id is None:
            return None
        task = await self.tasks.get(ctx, item.existing_task_id)
        if task.scope != "project" or task.scope_id != room.project_id:
            raise NotFoundError(message="Task not found")
        if lock:
            table = await virtual_table_repo.get_table(
                self.db,
                task.table_id,
                organization_id=ctx.organization_id,
                for_share=True,
            )
            if table is None or table.archived_at is not None:
                raise NotFoundError(message="Task not found")
            record = await task_repo.record(self.db, task.id, ctx.organization_id, lock=True)
            if record is None:
                raise NotFoundError(message="Task not found")
            task = await self.tasks.get(ctx, task.id)
        if (
            task.revision != item.expected_task_revision
            or task.assignee_agent_id != item.agent_id
            or task.assignee_user_id != (item.accountable_user_id or ctx.user_id)
        ):
            raise AlreadyExistsError(
                message="The existing task changed; review its revision and assignees"
            )
        return task

    async def _validate_item(
        self,
        ctx: AuthContext,
        room: Conversation,
        policy: RoomLeadPolicy,
        item: RoomProposalItem,
    ) -> RoomProposalItem:
        permitted = {
            (UUID(value["agent_id"]), UUID(value["version_id"])) for value in policy.specialists
        }
        if (item.agent_id, item.agent_version_id) not in permitted:
            raise BadRequestError(message="Choose one of the room policy's pinned specialists")
        pin = await self._pin(ctx, item.agent_id, item.agent_version_id)
        if not pin.current:
            raise AlreadyExistsError(
                message="A specialist version changed; update the room policy and proposal"
            )
        if room.project_id is None or not await scope_allows(
            self.db, ctx, "project", room.project_id, edit=True
        ):
            raise AuthorizationError(
                message="Creating room handoffs requires access to the project's task board"
            )
        owner_id = item.accountable_user_id or ctx.user_id
        owner = await acting_member(self.db, ctx.organization_id, str(owner_id))
        if owner is None or not await scope_allows(
            self.db, owner, "project", room.project_id, edit=True
        ):
            raise BadRequestError(
                message="Choose an accountable person who can edit this project's tasks"
            )
        await self.rooms.room(owner, room.id, for_write=True)
        if owner.user_id != ctx.user_id:
            await self._pin(owner, item.agent_id, item.agent_version_id)
        normalized = item.model_copy(update={"accountable_user_id": owner_id})
        await self._existing(ctx, room, normalized)
        return normalized

    async def planner(self, submission: RoomSubmission) -> RoomLeadPlanning:
        ctx, _, _ = await self.rooms.authority(submission)
        policy = await self.submission_policy(ctx, submission)
        specialists = []
        for value in policy.specialists:
            pin = await self._read_pin(ctx, RoomAgentPin.model_validate(value))
            if pin is not None and pin.current:
                specialists.append(pin.model_dump(mode="json"))
        organization_id, submission_id = submission.organization_id, submission.id

        async def write(run_id: UUID, request: RoomProposalCreate) -> RoomRoutingProposalRead:
            from app.db.session import get_worker_db_context

            async with get_worker_db_context() as fresh:
                return await RoomRoutingService(fresh).propose(
                    organization_id,
                    submission_id,
                    run_id,
                    request,
                )

        return RoomLeadPlanning(
            context=json.dumps(
                {
                    "requester_id": str(submission.requester_id),
                    "max_items": policy.max_items,
                    "specialists": specialists,
                }
            ),
            create_proposal=write,
        )

    async def propose(
        self,
        organization_id: UUID,
        submission_id: UUID,
        run_id: UUID,
        data: RoomProposalCreate,
    ) -> RoomRoutingProposalRead:
        submission = await room_repo.get(self.db, submission_id, organization_id=organization_id)
        if submission is None or submission.run_id != run_id or submission.status != "running":
            raise NotFoundError(message="The planning request is unavailable")
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, submission.conversation_id)
        submission = await room_repo.get(
            self.db,
            submission_id,
            organization_id=organization_id,
            lock=True,
        )
        if submission is None or submission.run_id != run_id or submission.status != "running":
            raise NotFoundError(message="The planning request is unavailable")
        ctx, room, message = await self.rooms.authority(submission)
        policy = await self.submission_policy(ctx, submission)
        if len(data.items) > policy.max_items:
            raise BadRequestError(
                message=f"This room permits at most {policy.max_items} proposed handoffs"
            )
        items = [await self._validate_item(ctx, room, policy, item) for item in data.items]
        encoded = [item.model_dump(mode="json") for item in items]
        hashed = _digest(encoded)
        existing = await routing_repo.for_submission(
            self.db,
            submission.id,
            organization_id=organization_id,
            conversation_id=room.id,
        )
        if existing is not None:
            if existing.proposal_hash != hashed:
                raise AlreadyExistsError(
                    message="This Ask lead request already has a different proposal"
                )
            return await self._read(ctx, room, existing)
        row = RoomRoutingProposal(
            id=uuid4(),
            organization_id=organization_id,
            conversation_id=room.id,
            submission_id=submission.id,
            message_id=message.id,
            thread_root_message_id=message.thread_root_message_id,
            requester_id=submission.requester_id,
            lead_run_id=run_id,
            policy_revision=policy.revision,
            revision=1,
            proposal_hash=hashed,
            items=[
                {**item, "proposal_item_id": str(uuid5(submission.id, f"handoff:{index}"))}
                for index, item in enumerate(encoded)
            ],
            decision="pending",
            accepted_item_ids=[],
        )
        await routing_repo.save(self.db, row)
        announce_request(self.db, submission)
        return await self._read(ctx, room, row)

    async def _read(
        self,
        ctx: AuthContext,
        room: Conversation,
        row: RoomRoutingProposal,
    ) -> RoomRoutingProposalRead:
        items = []
        for value in row.items:
            item = _stored_item(value)
            visible_task = None
            if item.existing_task_id is not None:
                with suppress(AppException):
                    visible_task = await self.tasks.get(ctx, item.existing_task_id)
            items.append(
                RoomProposalItemRead(
                    proposal_item_id=UUID(str(value["proposal_item_id"])),
                    title=item.title,
                    expected_result=item.expected_result,
                    accountable_user_id=item.accountable_user_id,
                    accountable_user_name=await self._accountable_name(
                        ctx, item.accountable_user_id, room.project_id
                    ),
                    due_at=item.due_at,
                    agent=await self._read_pin(
                        ctx,
                        RoomAgentPin(agent_id=item.agent_id, version_id=item.agent_version_id),
                    ),
                    existing_task_id=None if visible_task is None else visible_task.id,
                    expected_task_revision=None
                    if visible_task is None
                    else item.expected_task_revision,
                )
            )
        own = ctx.user_id == row.requester_id and row.decision == "pending"
        can_decide = False
        if own:
            try:
                await self.rooms.room(ctx, room.id, for_write=True)
                can_decide = True
            except AppException:
                pass
        policy = (
            await routing_repo.policy(self.db, ctx.organization_id, room.id) if can_decide else None
        )
        submission = (
            await room_repo.get(self.db, row.submission_id, organization_id=ctx.organization_id)
            if can_decide
            else None
        )
        return RoomRoutingProposalRead(
            id=row.id,
            conversation_id=row.conversation_id,
            thread_root_message_id=row.thread_root_message_id,
            submission_id=row.submission_id,
            message_id=row.message_id,
            requester_id=row.requester_id,
            lead_run_id=row.lead_run_id,
            policy_revision=row.policy_revision,
            revision=row.revision,
            decision=row.decision,
            items=items,
            accepted_item_ids=[UUID(value) for value in row.accepted_item_ids],
            can_accept=bool(
                can_decide
                and policy is not None
                and policy.enabled
                and policy.revision == row.policy_revision
                and submission is not None
                and submission.status == "completed"
            ),
            can_discard=can_decide,
            created_at=row.created_at,
        )

    async def read(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        proposal_id: UUID,
    ) -> RoomRoutingProposalRead:
        signed_in(ctx)
        room = await self.rooms.room(ctx, conversation_id)
        row = await routing_repo.proposal(
            self.db,
            proposal_id,
            organization_id=ctx.organization_id,
            conversation_id=conversation_id,
        )
        if row is None:
            raise NotFoundError(message="Room routing proposal not found")
        return await self._read(ctx, room, row)

    async def list(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        *,
        thread_root_message_id: UUID | None,
        limit: int,
        skip: int = 0,
    ) -> RoomRoutingProposalList:
        signed_in(ctx)
        room = await self.rooms.room(ctx, conversation_id)
        await self._thread(conversation_id, thread_root_message_id)
        rows = await routing_repo.proposals(
            self.db,
            organization_id=ctx.organization_id,
            conversation_id=conversation_id,
            thread_root_message_id=thread_root_message_id,
            limit=limit,
            skip=skip,
        )
        return RoomRoutingProposalList(
            items=[await self._read(ctx, room, row) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )

    async def _decision(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        proposal_id: UUID,
        data: RoomProposalAccept | RoomProposalDiscard,
        action: str,
    ) -> tuple[Conversation, RoomRoutingProposal, bool, str]:
        signed_in(ctx)
        room = await self.rooms.room(ctx, conversation_id, for_write=True)
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        row = await routing_repo.proposal(
            self.db,
            proposal_id,
            organization_id=ctx.organization_id,
            conversation_id=conversation_id,
            lock=True,
        )
        if row is None:
            raise NotFoundError(message="Room routing proposal not found")
        if ctx.user_id != row.requester_id:
            raise AuthorizationError(message="Only the requester may decide this routing proposal")
        body = data.model_dump(mode="json")
        if isinstance(data, RoomProposalAccept):
            body["selected_item_ids"] = sorted(body["selected_item_ids"])
        decision_hash = _digest({"action": action, "body": body})
        if row.decision != "pending":
            if row.decision_key == data.idempotency_key and row.decision_hash == decision_hash:
                return room, row, True, decision_hash
            raise AlreadyExistsError(
                message="This routing proposal already has a different decision"
            )
        if row.revision != data.expected_revision:
            raise AlreadyExistsError(
                message="The routing proposal changed; review its current revision"
            )
        return room, row, False, decision_hash

    async def accept(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        proposal_id: UUID,
        data: RoomProposalAccept,
    ) -> RoomRoutingProposalRead:
        room, row, replayed, decision_hash = await self._decision(
            ctx, conversation_id, proposal_id, data, "accepted"
        )
        if replayed:
            return await self._read(ctx, room, row)
        submission = await room_repo.get(
            self.db, row.submission_id, organization_id=ctx.organization_id
        )
        if (
            submission is None
            or submission.status != "completed"
            or submission.run_id != row.lead_run_id
        ):
            raise AlreadyExistsError(
                message="The lead must finish this request before its proposal is accepted"
            )
        original, source_room, _ = await self.rooms.authority(submission)
        if original.user_id != ctx.user_id or source_room.id != room.id:
            raise NotFoundError(message="The original planning request is unavailable")
        policy = await self.submission_policy(ctx, submission)
        if policy.revision != row.policy_revision:
            raise AlreadyExistsError(message="The room policy changed after this proposal")
        selected = set(data.selected_item_ids)
        by_id = {UUID(str(value["proposal_item_id"])): _stored_item(value) for value in row.items}
        if not selected <= by_id.keys():
            raise BadRequestError(message="Choose only items from this routing proposal")
        # Stable ordering also serializes two rooms referencing the same task set.
        for item_id in sorted(selected, key=lambda key: str(by_id[key].existing_task_id or key)):
            item = await self._validate_item(ctx, room, policy, by_id[item_id])
            task = await self._existing(ctx, room, item, lock=True)
            dispatch = None
            if task is None:
                task = await self.tasks.create(
                    ctx,
                    TaskCreate(
                        scope="project",
                        scope_id=room.project_id,
                        title=item.title,
                        description=item.expected_result,
                        assignee_user_id=item.accountable_user_id,
                        assignee_agent_id=item.agent_id,
                        due_at=item.due_at,
                        next_actor="agent" if item.accountable_user_id == ctx.user_id else "user",
                        external_id=f"room-routing:{row.id}:{item_id}",
                    ),
                )
                if item.accountable_user_id == ctx.user_id:
                    binding = await task_repo.link(self.db, task.id)
                    dispatch = None if binding is None else binding.trigger_id
                    if (
                        dispatch is None
                        or await routing_repo.dispatch_version(
                            self.db,
                            dispatch,
                            organization_id=ctx.organization_id,
                        )
                        != item.agent_version_id
                    ):
                        raise AlreadyExistsError(
                            message="The specialist version changed during acceptance"
                        )
            await routing_repo.save(
                self.db,
                RoomTaskLink(
                    id=uuid4(),
                    organization_id=ctx.organization_id,
                    conversation_id=room.id,
                    proposal_id=row.id,
                    proposal_item_id=item_id,
                    task_id=task.id,
                    table_id=task.table_id,
                    requester_id=ctx.subject_id,
                    accepted_revision=task.revision,
                    idempotency_key=data.idempotency_key,
                    dispatch_trigger_id=dispatch,
                    provenance={
                        "kind": "room_lead",
                        "proposal_id": str(row.id),
                        "proposal_item_id": str(item_id),
                        "policy_revision": row.policy_revision,
                        "specialist_agent_id": str(item.agent_id),
                        "specialist_version_id": str(item.agent_version_id),
                        "requester_id": str(ctx.subject_id),
                        "accepted_revision": task.revision,
                    },
                ),
            )
        row.decision, row.decision_key, row.decision_hash = (
            "accepted",
            data.idempotency_key,
            decision_hash,
        )
        row.accepted_item_ids = [str(value) for value in sorted(selected)]
        row.revision += 1
        await routing_repo.save(self.db, row)
        announce_request(self.db, submission)
        return await self._read(ctx, room, row)

    async def discard(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        proposal_id: UUID,
        data: RoomProposalDiscard,
    ) -> RoomRoutingProposalRead:
        room, row, replayed, decision_hash = await self._decision(
            ctx, conversation_id, proposal_id, data, "discarded"
        )
        if not replayed:
            row.decision, row.decision_key, row.decision_hash = (
                "discarded",
                data.idempotency_key,
                decision_hash,
            )
            row.revision += 1
            await routing_repo.save(self.db, row)
            submission = await room_repo.get(
                self.db, row.submission_id, organization_id=ctx.organization_id
            )
            if submission is not None:
                announce_request(self.db, submission)
        return await self._read(ctx, room, row)

    async def task_cards(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        *,
        thread_root_message_id: UUID | None,
        limit: int,
        skip: int = 0,
    ) -> RoomTaskCardList:
        signed_in(ctx)
        room = await self.rooms.room(ctx, conversation_id)
        await self._thread(conversation_id, thread_root_message_id)
        rows = await routing_repo.task_links(
            self.db,
            organization_id=ctx.organization_id,
            conversation_id=conversation_id,
            thread_root_message_id=thread_root_message_id,
            limit=limit,
            skip=skip,
        )
        cards = []
        for link, proposal in rows[:limit]:
            try:
                task = await self.tasks.get(ctx, link.task_id)
            except AppException:
                continue
            agent = None
            if task.assignee_agent_id is not None:
                with suppress(AppException):
                    agent = await self._pin(ctx, task.assignee_agent_id)
            cards.append(
                RoomTaskCard(
                    id=link.id,
                    proposal_id=proposal.id,
                    proposal_item_id=link.proposal_item_id,
                    message_id=proposal.message_id,
                    thread_root_message_id=proposal.thread_root_message_id,
                    task_id=task.id,
                    table_id=task.table_id,
                    accepted_revision=link.accepted_revision,
                    revision=task.revision,
                    title=task.title,
                    description=task.description,
                    status=task.status,
                    next_actor=task.next_actor,
                    accountable_user_id=task.assignee_user_id,
                    accountable_user_name=await self._accountable_name(
                        ctx, task.assignee_user_id, room.project_id
                    ),
                    agent=agent,
                    due_at=task.due_at,
                )
            )
        return RoomTaskCardList(items=cards, has_more=len(rows) > limit)
