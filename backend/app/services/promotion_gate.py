"""The promotion gate: an environment takes a version only once its eval suites pass on it.

An environment names the suites that guard it. A version is let onto it when
every guard has a passing result on that exact version, over the dataset
version the suite reads now and under the threshold it holds now - so a pass
from before cases were added, or before the bar was raised, does not count.
Anything else stops the promotion, and the refusal carries the whole gate:
which guard, in what state, with the result behind it.

Somebody holding `promotions:override` may promote past the guards anyway,
signed in as themselves and saying why. The override is written to the audit
log and kept on the version, and each guard's owner hears of it.

An environment that follows publishes and names guards does not move on the
publish: its guards are queued on the new version, and the sweep moves it once
the last of them passes.
"""

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.background import spawn_after_commit
from app.core.exceptions import AuthorizationError, PromotionBlockedError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.eval_suite import EvalSuite, EvalSuiteResult, EvalSuiteResultStatus
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    dataset_repo,
    eval_run_repo,
    eval_suite_repo,
    member_repo,
    promotion_gate_repo,
)
from app.schemas.change_event import ChangeEvent
from app.schemas.promotion_gate import (
    GuardState,
    PromotionGateRead,
    PromotionGateRun,
    PromotionGateRunRead,
    PromotionGuardRead,
    PromotionGuardRecord,
    PromotionOverrideRead,
)
from app.services import change_feed

if TYPE_CHECKING:
    from app.db.models.promotion_gate import PromotionOverride

logger = logging.getLogger(__name__)

# Guarded followers the sweep looks at in one tick.
_RECONCILE_LIMIT = 200

_SETTLED_STATES: dict[str, GuardState] = {
    EvalSuiteResultStatus.BASELINE_SET.value: "inconclusive",
    EvalSuiteResultStatus.FAILED.value: "failed",
    EvalSuiteResultStatus.INCONCLUSIVE.value: "inconclusive",
    EvalSuiteResultStatus.SKIPPED.value: "skipped",
    EvalSuiteResultStatus.ERROR.value: "error",
}


def guard_state(
    suite: EvalSuite,
    settled: tuple[EvalSuiteResult, int | None, str | None, UUID | None, bool | None] | None,
    waiting: EvalSuiteResult | None,
    *,
    dataset_version: int,
    scoring_hash: str,
) -> tuple[GuardState, EvalSuiteResult | None]:
    """Where one guard stands on a version, and the result that says so.

    `settled` is its last settled result there beside the environment's
    version, with the number of the dataset version that result's run read and
    the scoring it was graded under; `waiting` is such a result still to start
    or finish; `dataset_version` and `scoring_hash` are what the suite would
    read and grade by now. A paused guard holds the version back whatever it
    found before the pause, and so does one not pinned to a dataset version yet.
    """
    from app.services.eval_suite import threshold_of

    if not suite.is_active:
        return "paused", settled[0] if settled is not None else waiting
    if suite.pinned_dataset_version is None:
        return "unpinned", settled[0] if settled is not None else waiting
    if settled is not None:
        result, number, hashed, judge_version, pinned = settled
        current = (
            result.dataset_id == suite.dataset_id
            and result.threshold == threshold_of(suite).model_dump(mode="json")
            and number in (None, dataset_version)
            and hashed in (None, scoring_hash)
            and (
                number is None
                or (pinned is True and judge_version == suite.pinned_judge_version_id)
            )
        )
        if (
            current
            and result.status == EvalSuiteResultStatus.PASSED.value
            and number == dataset_version
            and hashed == scoring_hash
        ):
            return "passed", result
    if waiting is not None:
        return "checking", waiting
    if settled is None:
        return "unchecked", None
    if not current or result.status == EvalSuiteResultStatus.PASSED.value:
        return "stale", result
    return _SETTLED_STATES[result.status], result


class PromotionGateService:
    """Reads an environment's gate for a version, enforces it, and moves the
    guarded environments that follow publishes once their guards pass."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def read(
        self, ctx: AuthContext, agent_id: UUID, environment_id: UUID, version_id: UUID
    ) -> PromotionGateRead:
        """The gate for promoting this version onto this environment.

        Read by whoever may promote the agent: what stops a promotion is the
        promoter's business.
        """
        agent, environment = await self._environment(ctx, agent_id, environment_id)
        version = await self._version(ctx, agent, version_id)
        return await self.check(ctx, agent=agent, environment=environment, version=version)

    async def check(
        self,
        ctx: AuthContext | None,
        *,
        agent: Agent,
        environment: AgentEnvironment,
        version: AgentVersion,
    ) -> PromotionGateRead:
        """Each guard of the environment on the version.

        With no caller - the sweep deciding whether an environment may follow -
        the failing cases are left out, as nobody is reading them.
        """
        from app.services.eval_run import scoring_hash
        from app.services.eval_suite import EvalSuiteService, reads_now

        org = agent.organization_id
        serving = await agent_repo.get_version(self.db, environment.version_id, organization_id=org)
        assert serving is not None, "an environment is always pinned"
        suite_ids = (
            await promotion_gate_repo.guards_for(self.db, [environment.id], organization_id=org)
        ).get(environment.id, [])
        suites = [
            suite
            for suite_id in suite_ids
            if (suite := await eval_suite_repo.get(self.db, suite_id, organization_id=org))
        ]
        datasets = await eval_run_repo.datasets(
            self.db, sorted({suite.dataset_id for suite in suites}), organization_id=org
        )
        settled = await eval_suite_repo.settled_on_version(
            self.db, suite_ids, version.id, baseline_version=serving.version, organization_id=org
        )
        waiting = await eval_suite_repo.open_on_version(
            self.db, suite_ids, version.id, baseline_version=serving.version, organization_id=org
        )
        states = []
        for suite in suites:
            dataset_version, scoring = reads_now(suite, datasets[suite.dataset_id])
            state, result = guard_state(
                suite,
                settled.get(suite.id),
                waiting.get(suite.id),
                dataset_version=dataset_version,
                scoring_hash=scoring_hash(scoring),
            )
            states.append((suite, state, result))
        suites_service = EvalSuiteService(self.db)
        readable = (
            await suites_service.readable_datasets(
                ctx, [r.dataset_id for _, _, r in states if r and r.dataset_id]
            )
            if ctx is not None
            else set()
        )
        guards = [
            PromotionGuardRead(
                suite_id=suite.id,
                suite_name=suite.name,
                state=state,
                paused_reason=None if suite.is_active else suite.paused_reason,
                result=(
                    suites_service.result_read(result, cases_visible=result.dataset_id in readable)
                    if result is not None
                    else None
                ),
            )
            for suite, state, result in states
        ]
        return PromotionGateRead(
            environment_id=environment.id,
            environment_name=environment.name,
            version_id=version.id,
            version=version.version,
            guarded=bool(guards),
            passing=all(guard.state == "passed" for guard in guards),
            can_override=ctx is not None and self.may_override(ctx),
            guards=guards,
        )

    async def enforce(
        self,
        ctx: AuthContext,
        *,
        agent: Agent,
        environment: AgentEnvironment,
        version: AgentVersion,
        replaced_version_id: UUID,
        override_reason: str | None,
    ) -> None:
        """Refuse a promotion its guards do not pass, unless the caller overrides them.

        Raises:
            PromotionBlockedError: A guard has not passed on the version and the
                caller gave no reason or may not override; `details.gate` is
                the gate.
        """
        gate = await self.check(ctx, agent=agent, environment=environment, version=version)
        if gate.passing:
            return
        blocking = [guard.suite_name for guard in gate.guards if guard.state != "passed"]
        if override_reason is None or not gate.can_override:
            refused = (
                " Promoting past them needs permission to override promotions."
                if override_reason is not None
                else ""
            )
            raise PromotionBlockedError(
                message=(
                    f"v{version.version} has not passed {', '.join(repr(n) for n in blocking)}, "
                    f"which {'guards' if len(blocking) == 1 else 'guard'} {environment.name}."
                    f"{refused}"
                ),
                details={"gate": gate.model_dump(mode="json")},
            )
        await self._override(
            ctx,
            agent=agent,
            environment=environment,
            version=version,
            replaced_version_id=replaced_version_id,
            reason=override_reason,
            gate=gate,
        )

    async def set_guards(
        self,
        ctx: AuthContext,
        *,
        agent: Agent,
        environment: AgentEnvironment,
        suite_ids: list[UUID],
    ) -> bool:
        """Replace the suites guarding an environment; whether that changed them.

        Taking a guard off lets through what it would have stopped, so changing
        the set needs the same permission as promoting past it.
        """
        org = agent.organization_id
        wanted = list(dict.fromkeys(suite_ids))
        current = (
            await promotion_gate_repo.guards_for(self.db, [environment.id], organization_id=org)
        ).get(environment.id, [])
        if set(wanted) == set(current):
            return False
        if not self.may_override(ctx):
            raise AuthorizationError(
                message=(
                    "Changing which eval suites guard an environment needs permission "
                    "to override promotions"
                ),
                details={"permission": Perm.PROMOTIONS_OVERRIDE.value},
            )
        for suite_id in wanted:
            suite = await eval_suite_repo.get(self.db, suite_id, organization_id=org)
            if suite is None or suite.agent_id != agent.id:
                raise refused_field(
                    "guard_suite_ids", "A guard must be one of this agent's eval suites."
                )
            if suite_id not in current:
                await self._refuse_empty_dataset(suite)
        await promotion_gate_repo.replace_guards(
            self.db, environment.id, wanted, organization_id=org
        )
        await self.pin_guards(
            guarding=set(wanted), removed=set(current) - set(wanted), organization_id=org
        )
        if environment.tracks_latest:
            # The guard taken off may have been the last one holding it back.
            newest = await agent_repo.newest_version(
                self.db, agent_id=agent.id, organization_id=org
            )
            assert newest is not None, "an environment pins a version"
            await self._advance(agent, environment, newest)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=org,
            action="agent.environment_guards_changed",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "environment_id": str(environment.id),
                "name": environment.name,
                "added": [str(suite_id) for suite_id in wanted if suite_id not in current],
                "removed": [str(suite_id) for suite_id in current if suite_id not in wanted],
            },
        )
        return True

    async def _refuse_empty_dataset(self, suite: EvalSuite) -> None:
        """A guard is pinned to a dataset version, so a dataset with none yet cannot have one.

        Such a guard could not pass anyway; set up, it would read whatever the
        dataset's first cases turned out to be.
        """
        dataset = await dataset_repo.get(
            self.db, suite.dataset_id, organization_id=suite.organization_id
        )
        assert dataset is not None, "a suite's dataset outlives it"
        if dataset.latest_version == 0:
            raise refused_field(
                "guard_suite_ids",
                f"'{suite.name}': this suite's dataset has no cases yet. Add cases before it "
                "guards an environment.",
            )

    async def pin_guards(
        self, *, guarding: set[UUID], removed: set[UUID], organization_id: UUID
    ) -> None:
        """Pin each guard not pinned yet, and unpin a suite that guards nothing now.

        A guard checks what it was set up with until somebody who may override
        promotions moves it; a suite guarding nothing reads the latest. Each
        suite is locked, so two changes to the guards at once cannot leave one
        guarding unpinned.
        """
        from app.services.eval_suite import pin_to_latest, unpin

        for suite_id in sorted(guarding | removed):
            suite = await eval_suite_repo.lock(self.db, suite_id, organization_id=organization_id)
            if suite is None:
                continue
            guards = suite_id in guarding or bool(
                await promotion_gate_repo.guarded_by(
                    self.db, suite_id, organization_id=organization_id
                )
            )
            if guards and suite.pinned_dataset_version is None:
                await pin_to_latest(self.db, suite)
            elif not guards and suite.pinned_dataset_version is not None:
                await unpin(self.db, suite)

    async def run(
        self, ctx: AuthContext, agent_id: UUID, environment_id: UUID, data: PromotionGateRun
    ) -> PromotionGateRunRead:
        """Run each guard that has not passed and is not already checking, on the
        version, beside the one the environment serves now."""
        from app.services.eval_suite import EvalSuiteService

        agent, environment = await self._environment(ctx, agent_id, environment_id)
        version = await self._version(ctx, agent, data.version_id)
        gate = await self.check(ctx, agent=agent, environment=environment, version=version)
        serving = await agent_repo.get_version(
            self.db, environment.version_id, organization_id=agent.organization_id
        )
        suites = EvalSuiteService(self.db)
        started = []
        for guard in gate.guards:
            if guard.state in ("passed", "checking", "paused", "unpinned"):
                continue
            await suites.run_on_version(
                ctx,
                agent.id,
                guard.suite_id,
                version=version,
                baseline_version=serving.version if serving is not None else None,
            )
            started.append(guard.suite_id)
        return PromotionGateRunRead(
            started=started,
            gate=await self.check(ctx, agent=agent, environment=environment, version=version),
        )

    async def follow(self, *, organization_id: UUID, agent_id: UUID, version_id: UUID) -> None:
        """Move each guarded environment that follows publishes onto this version,
        once every one of its guards has passed on it.

        Only forwards: an environment already on a newer version stays there.
        The publish of the version already withdrew the trigger consents it had
        to, so moving onto it later withdraws none.
        """
        version = await agent_repo.get_version(self.db, version_id, organization_id=organization_id)
        agent = await agent_repo.get(self.db, agent_id, organization_id=organization_id)
        assert version is not None and agent is not None, "a result names its agent's version"
        for environment in await promotion_gate_repo.guarded_following_latest(
            self.db, agent.id, organization_id=organization_id
        ):
            await self._advance(agent, environment, version)

    async def reconcile(self) -> int:
        """Move every guarded follower whose guards all pass on its agent's newest
        version - the sweep's second look.

        The settlement that should have moved it may have seen a sibling guard
        still running in another transaction, or failed after the pass was
        written; either way the next tick finds it here.
        """
        moved = 0
        for environment in await promotion_gate_repo.guarded_followers(
            self.db, limit=_RECONCILE_LIMIT
        ):
            org = environment.organization_id
            agent = await agent_repo.get(self.db, environment.agent_id, organization_id=org)
            newest = await agent_repo.newest_version(
                self.db, agent_id=environment.agent_id, organization_id=org
            )
            assert agent is not None and newest is not None, "an environment pins a version"
            if await self._advance(agent, environment, newest):
                moved += 1
        return moved

    async def _advance(
        self, agent: Agent, environment: AgentEnvironment, version: AgentVersion
    ) -> bool:
        """Move a following environment onto a newer version its guards all pass."""
        from app.services.eval_suite import EvalSuiteService

        org = agent.organization_id
        serving = await agent_repo.get_version(self.db, environment.version_id, organization_id=org)
        assert serving is not None, "an environment is always pinned"
        if serving.version >= version.version:
            return False
        gate = await self.check(None, agent=agent, environment=environment, version=version)
        if not gate.passing:
            return False
        replaced = environment.version_id
        environment = await agent_environment_repo.update(
            self.db, environment=environment, update_data={"version_id": version.id}
        )
        if environment.is_default:
            await agent_repo.update(
                self.db, agent=agent, update_data={"current_version_id": version.id}
            )
        await EvalSuiteService(self.db).environment_promoted(
            agent=agent,
            environment=environment,
            version=version,
            replaced_version_id=replaced,
        )
        await record_audit(
            self.db,
            actor_user_id=None,
            organization_id=org,
            action="agent.environment_promoted",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "environment_id": str(environment.id),
                "name": environment.name,
                "version": version.version,
                "by": "gate",
                "passed": [guard.suite_name for guard in gate.guards],
            },
        )
        # Open consoles hear of it as of any change to the agent: the History
        # tab reads the environments under it.
        spawn_after_commit(
            self.db,
            change_feed.publish(
                ChangeEvent(
                    organization_id=org,
                    resource="agent",
                    id=agent.id,
                    action="updated",
                    surface="run",
                    actor_user_id=None,
                    actor_name=None,
                )
            ),
            name=f"promotion-gate-advance:{environment.id}",
        )
        return True

    async def overrides(
        self, ctx: AuthContext, version_ids: list[UUID]
    ) -> dict[UUID, list[PromotionOverrideRead]]:
        """The overrides made on each of these versions, as the history shows them."""
        rows = await promotion_gate_repo.overrides_for_versions(
            self.db, version_ids, organization_id=ctx.organization_id
        )
        users = sorted({o.user_id for found in rows.values() for o in found if o.user_id})
        emails = await member_repo.get_emails_for_users(
            self.db, organization_id=ctx.organization_id, user_ids=users
        )
        return {
            version_id: [self._override_read(o, emails) for o in found]
            for version_id, found in rows.items()
        }

    @staticmethod
    def _override_read(
        override: PromotionOverride, emails: dict[UUID, str | None]
    ) -> PromotionOverrideRead:
        return PromotionOverrideRead(
            id=override.id,
            environment_id=override.environment_id,
            environment_name=override.environment_name,
            user_id=override.user_id,
            user_email=emails.get(override.user_id) if override.user_id else None,
            reason=override.reason,
            guards=[PromotionGuardRecord.model_validate(guard) for guard in override.gate],
            created_at=override.created_at,
        )

    async def _override(
        self,
        ctx: AuthContext,
        *,
        agent: Agent,
        environment: AgentEnvironment,
        version: AgentVersion,
        replaced_version_id: UUID,
        reason: str,
        gate: PromotionGateRead,
    ) -> None:
        from app.services.notifications import NotificationService

        guards = [
            PromotionGuardRecord(
                suite_id=guard.suite_id,
                suite_name=guard.suite_name,
                state=guard.state,
                result_id=guard.result.id if guard.result else None,
            ).model_dump(mode="json")
            for guard in gate.guards
        ]
        override = await promotion_gate_repo.add_override(
            self.db,
            organization_id=agent.organization_id,
            values={
                "agent_id": agent.id,
                "version_id": version.id,
                "environment_id": environment.id,
                "environment_name": environment.name,
                "replaced_version_id": replaced_version_id,
                "user_id": ctx.user_id,
                "reason": reason,
                "gate": guards,
            },
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=agent.organization_id,
            action="agent.environment_promotion_overridden",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "override_id": str(override.id),
                "environment_id": str(environment.id),
                "name": environment.name,
                "version": version.version,
                "reason": reason,
                "guards": guards,
            },
        )
        owners = set()
        for guard in gate.guards:
            if guard.state == "passed":
                continue
            suite = await eval_suite_repo.get(
                self.db, guard.suite_id, organization_id=agent.organization_id
            )
            if suite is not None and suite.owner_user_id not in (None, ctx.user_id):
                owners.add(suite.owner_user_id)
        await NotificationService(self.db).promotion_overridden(
            override, agent=agent, version=version, owners=sorted(owners)
        )

    @staticmethod
    def may_override(ctx: AuthContext) -> bool:
        """An override is a person's decision: signed in as themselves, holding the permission."""
        return (
            ctx.user_id is not None
            and ctx.api_key_id is None
            and current_impersonator() is None
            and ctx.has(Perm.PROMOTIONS_OVERRIDE)
        )

    async def _environment(
        self, ctx: AuthContext, agent_id: UUID, environment_id: UUID
    ) -> tuple[Agent, AgentEnvironment]:
        from app.services.agent_environment import AgentEnvironmentService

        return await AgentEnvironmentService(self.db).get_environment(ctx, agent_id, environment_id)

    async def _version(self, ctx: AuthContext, agent: Agent, version_id: UUID) -> AgentVersion:
        from app.services.agent_environment import AgentEnvironmentService

        return await AgentEnvironmentService(self.db).version_of(ctx, agent, version_id)
