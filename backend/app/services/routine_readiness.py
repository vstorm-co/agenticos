"""Whether a routine's next activation would run, asked of the checks a fire makes.

Nothing here decides admission. Each blocker is the answer one of the fire path's
own checks gives, asked without the side effects a fire has: the creator's
membership (`_creator_context`), the agent's run grant, the runnable version, the
source review (`RoutineSourceService.current`, the read half of
`require_current`), the action consents (`RoutineActionService.review`, the
review the consent dialog shows) and the parked run the schedule waits behind
(`claim_due`'s busy rule). A check that can only be answered by a provider at run
time is not predicted; its refusal is in the routine's attempt history.
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import RunStatus
from app.db.models.agent_trigger import AgentTrigger, TriggerOverlap
from app.repositories import agent_run_repo
from app.schemas.routine_readiness import RoutineBlocker
from app.services.agent_registry import AgentRegistryService
from app.services.routine_actions import RoutineActionService
from app.services.routine_sources import (
    PlatformRoutineIdentityRequired,
    RoutineSourceService,
    read_policy,
    source_scope,
)

_PARKED = frozenset({RunStatus.AWAITING_APPROVAL.value, RunStatus.AWAITING_ANSWER.value})


async def blockers(
    db: AsyncSession,
    trigger: AgentTrigger,
    *,
    creator: AuthContext | None,
    paused_for_budget: bool,
) -> list[RoutineBlocker]:
    """What stops `trigger`'s next activation, evaluated as `creator` would run it.

    `creator` is None when the creator has no active membership; nothing else can
    then be evaluated, because every later check runs under their authority.
    """
    found: list[RoutineBlocker] = []
    if trigger.ends_at is not None and trigger.ends_at <= datetime.now(UTC):
        found.append(RoutineBlocker(code="ended", severity="blocked"))
    if paused_for_budget:
        found.append(RoutineBlocker(code="budget_exhausted", severity="blocked"))
    if creator is None:
        found.append(RoutineBlocker(code="creator_inactive", severity="blocked"))
        return found
    agents = AgentRegistryService(db)
    try:
        await agents.get(creator, trigger.agent_id, perm=Perm.AGENTS_RUN)
    except NotFoundError, AuthorizationError:
        found.append(RoutineBlocker(code="creator_cannot_run", severity="blocked"))
        return found
    try:
        if trigger.pinned_version_id is not None:
            await agents.get_pinned_spec(creator, trigger.agent_id, trigger.pinned_version_id)
        else:
            await agents.get_runnable_spec(
                creator, trigger.agent_id, environment_id=trigger.environment_id
            )
    except NotFoundError, BadRequestError:
        found.append(RoutineBlocker(code="agent_unavailable", severity="blocked"))
        return found
    following = False
    scope_changed = False
    if trigger.setup_required:
        found.append(RoutineBlocker(code="sources_setup", severity="blocked"))
    else:
        try:
            policy = read_policy(trigger.approved_sources)
            # A stale review still says how the routine is reviewed: re-reviewing a
            # following routine does not make standing consent apply to it.
            following = policy.mode == "follow_agent"
            # Who it acts as, where it reads from or delivers to is part of what was
            # reviewed, so editing the routine itself is a reason of its own.
            scope_changed = policy.scope_hash != source_scope(trigger)
            await RoutineSourceService(db).current(creator, trigger, expected_id=policy.id)
        except PlatformRoutineIdentityRequired:
            found.append(RoutineBlocker(code="platform_identity", severity="blocked"))
        except AuthorizationError, NotFoundError, BadRequestError:
            # The fire path reads every one of these as a source review to redo.
            found.append(
                RoutineBlocker(
                    code="routine_changed" if scope_changed else "sources_review",
                    severity="blocked",
                )
            )
    parked = await _parked_run(db, trigger)
    if parked is not None:
        found.append(parked)
    # A following review defers effects to the agent's own approval gate, where
    # standing consent has no say (`RoutineAuthority.action_policy`).
    if not following:
        waiting = await _unconsented_actions(db, creator, trigger)
        if waiting:
            found.append(
                RoutineBlocker(code="actions_need_approval", severity="attention", count=waiting)
            )
    return found


async def _parked_run(db: AsyncSession, trigger: AgentTrigger) -> RoutineBlocker | None:
    """The previous run, while it waits on a person.

    A schedule that does not overlap is held behind it (`claim_due`), so it fires
    nothing until somebody decides; an event or an overlapping schedule still
    fires, and the parked run is only something to act on.
    """
    run = (
        await agent_run_repo.get_run(
            db, trigger.last_run_id, organization_id=trigger.organization_id
        )
        if trigger.last_run_id is not None
        else None
    )
    if (run is None or run.status not in _PARKED) and trigger.conversation_id is not None:
        run = await agent_run_repo.latest_parked_run_for_conversation(
            db, conversation_id=trigger.conversation_id, organization_id=trigger.organization_id
        )
    if run is None or run.status not in _PARKED:
        return None
    held = trigger.trigger_type == "schedule" and trigger.overlap != TriggerOverlap.ALLOW.value
    return RoutineBlocker(
        code="awaiting_approval"
        if run.status == RunStatus.AWAITING_APPROVAL.value
        else "awaiting_answer",
        severity="blocked" if held else "attention",
        run_id=run.id,
    )


async def _unconsented_actions(
    db: AsyncSession, creator: AuthContext, trigger: AgentTrigger
) -> int:
    """How many eligible actions would require approval if the agent uses them."""
    try:
        review = await RoutineActionService(db).review(creator, trigger)
    except NotFoundError, BadRequestError, AuthorizationError:
        # The version or a delegate is unavailable; the source review says so.
        return 0
    waivable = [item for item in review.items if item.waivable]
    if not review.can_waive:
        return len(waivable)
    return sum(1 for item in waivable if not item.consented)
