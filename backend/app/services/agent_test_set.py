"""An agent's test set, built from its rated conversations and graded on another model.

An improvement is measured on test questions, and most agents have none. This
builds one in a call: the answers people rated become questions - a thumbs-up
the good answer, a thumbs-down the answer to avoid, with its comment as the
note - and the case generator is asked for more, which become part of the test
set as soon as they are written, for a person to review afterwards. Grading is
set up with them: compared with the good answer, never the answer to avoid, by a
judge on another model than the agent's wherever the organization has one.

Nothing here commits. The improvement session calls it inside the step that
needs the test set, and the generation is a job queued in that same
transaction, so a step that fails leaves no dataset, no version and no job.

Questions taken from the conversations the improver learns from cannot measure
it: :meth:`AgentTestSetService.gradable_count` counts only the others.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.agents.system_agents import JUDGE
from app.core.exceptions import (
    AiAssistanceDisabledError,
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.credential import ModelProfile
from app.db.models.dataset import Dataset, DatasetCase
from app.repositories import agent_repo, agent_run_repo, credential_repo, dataset_repo
from app.schemas.agent_test_set import (
    AgentTestSetBootstrap,
    AgentTestSetCounts,
    AgentTestSetEstimate,
    AgentTestSetJudge,
    GenerationSkipped,
    JudgeReason,
)
from app.schemas.case_generation import MAX_GENERATED, CaseGenerationRequest, CaseOriginLiteral
from app.schemas.dataset import AnswerAs, DatasetCreate
from app.schemas.resource_grant import as_visibility
from app.schemas.scoring import DatasetScoring, JudgeCreate
from app.services.access import DATASET, resolve_access
from app.services.agent_registry import AgentRegistryService
from app.services.ai_assistance import AiAssistanceService
from app.services.case_generation import CaseGenerationService
from app.services.dataset import DatasetService
from app.services.rag.vectorstore import BaseVectorStore
from app.services.scoring import STARTING_CRITERION, ScoringService
from app.services.system_agent_runner import SystemAgentRunner

TOO_FEW = 3
"""Below this many gradable questions, a change cannot be measured."""
TARGET = 5
"""How many gradable questions the generator is asked to bring the test set up to."""
RATED_LIMIT = 50
"""At most this many rated answers are added in one build."""
CANDIDATES = 500
"""How many rated answers a build reads through to find them."""
_NAME_TRIES = 10

REASONS: dict[JudgeReason, str] = {
    "cannot_publish": (
        "An admin needs to publish an independent judge. Until then answers are graded "
        "by the default judge."
    ),
    "judge_off": (
        "The test set's judge is switched off, so answers are graded only by its checks "
        "and expected tool calls. It was left as it is; switch the judge on in its Grading tab."
    ),
    "unknown_model": (
        "This agent has no model set yet, so the standard grader is used and nothing "
        "shows whether it runs on another model."
    ),
    "shares_model": (
        "The test set's judge runs on the same model as the agent, or on one that cannot "
        "be told apart. Its grading was left as it is; pick another judge in its Grading tab."
    ),
    "one_model": (
        "Only one model is set up, so the grader runs on the same model as the agent. "
        "Add another model to have answers graded by a different one."
    ),
    "ai_off": (
        "AI assistance is off in this organization, so nothing compares answers with the "
        "good answers until an Owner or an Admin switches it on."
    ),
}


def is_gradable(case: DatasetCase, scoring: DatasetScoring) -> bool:
    """Whether some scorer the dataset has on can grade this case."""
    judge = scoring.judge.enabled and bool(scoring.judge.criteria)
    reference = scoring.reference.enabled and (
        case.reference_answer is not None or case.counter_example is not None
    )
    checks = scoring.checks.enabled and bool(case.checks or scoring.checks.defaults)
    trajectory = scoring.trajectory.enabled and bool(case.expected_tool_calls)
    return judge or reference or checks or trajectory


def _not_independent(reason: JudgeReason, *, kept: bool = False) -> AgentTestSetJudge:
    return AgentTestSetJudge(
        independent=False, reason=REASONS[reason], reason_code=reason, kept=kept
    )


def _same_model(one: ModelProfile | None, other: ModelProfile | None) -> bool:
    return (
        one is not None
        and other is not None
        and (one.provider, one.model) == (other.provider, other.model)
    )


class AgentTestSetService:
    """Build an agent's test set, and say how much of it can measure a change."""

    def __init__(self, db: AsyncSession, *, vector_store: BaseVectorStore) -> None:
        self.db = db
        self.datasets = DatasetService(db)
        self.scoring = ScoringService(db)
        self.generation = CaseGenerationService(db, vector_store=vector_store)

    async def bootstrap_for_agent(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        since: datetime | None = None,
        evidence_conversation_ids: Sequence[UUID] = (),
        more: int | None = None,
    ) -> AgentTestSetBootstrap:
        """Create the agent's test set, or add its newest rated answers to it.

        The test set is the newest dataset made for the agent that the caller
        may edit, or a new private one named after the agent - it copies other
        people's questions, so nobody else reads them until it is shared. Rated
        answers are added in one version, each question on its own - a
        conversation is not copied into a case nobody chose to keep it in. More
        questions are asked for
        until :data:`TARGET` can be graded outside the evidence conversations,
        or `more` of them whatever the count; they are written by a job and
        join the test set when ready, so `gradable` does not count them yet.

        Raises:
            AuthorizationError: The caller's role may not edit datasets.
            NotFoundError: The agent is not one the caller may see.
        """
        if not ctx.has(Perm.DATASETS_EDIT):
            raise AuthorizationError(
                message="Building a test set creates a dataset, which your role does not allow"
            )
        agent = await AgentRegistryService(self.db).get(ctx, agent_id)
        dataset, created = await self._dataset(ctx, agent)
        counts = await self._add_rated(ctx, dataset, agent_id, since)
        judge = await self._grade(ctx, dataset, agent, created=created)
        gradable = await self.gradable_count(
            ctx, dataset.id, evidence_conversation_ids=evidence_conversation_ids
        )
        generation_id, requested, skipped = await self._write_more(
            ctx, dataset.id, agent, gradable=gradable, more=more
        )
        counts.generated_requested = requested
        version = (await self.datasets.read(ctx, dataset.id)).latest_version
        return AgentTestSetBootstrap(
            dataset_id=dataset.id,
            visibility=as_visibility(dataset.visibility),
            version=version,
            created=created,
            counts=counts,
            generation_id=generation_id,
            generation_skipped=skipped,
            judge=judge,
            gradable=gradable,
            too_few=gradable < TOO_FEW,
        )

    async def gradable_count(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        *,
        evidence_conversation_ids: Sequence[UUID] = (),
    ) -> int:
        """Questions of the newest version that can measure a change.

        Those some scorer the dataset has on can grade - the judge only when it
        would run now, so a draft or archived one grades nothing - and that do not come
        from the evidence conversations - a question the improver learned from
        cannot measure it. Every rule of what does not count is here, so a later
        one - a held-out split - is added in one place.

        Raises:
            NotFoundError: The dataset is not one the caller may see.
        """
        dataset = await self.datasets.get(ctx, dataset_id)
        version = await dataset_repo.get_version(
            self.db, dataset.id, dataset.latest_version, organization_id=ctx.organization_id
        )
        if version is None:
            return 0
        scoring = DatasetScoring.model_validate(dataset.scoring)
        if not await self._judge_grades(ctx, scoring):
            scoring.judge.enabled = scoring.reference.enabled = False
        evidence = set(evidence_conversation_ids)
        cases = await dataset_repo.list_cases(
            self.db, version.id, organization_id=ctx.organization_id, limit=None
        )
        return sum(
            1
            for case in cases
            if case.source_conversation_id not in evidence and is_gradable(case, scoring)
        )

    async def _judge_grades(self, ctx: AuthContext, scoring: DatasetScoring) -> bool:
        """Whether the judge the dataset grades with would run now - published, on a model."""
        if not (scoring.judge.enabled or scoring.reference.enabled):
            return False
        try:
            await SystemAgentRunner(self.db).require_runnable(
                ctx, key=JUDGE.key, agent_id=scoring.judge.agent_id
            )
        except AiAssistanceDisabledError, SystemAgentUnavailableError:
            return False
        return True

    async def estimate_bootstrap(
        self, ctx: AuthContext, agent_id: UUID, *, more: int | None = None
    ) -> AgentTestSetEstimate:
        """What writing questions for the test set would cost, at most.

        Priced for `more` questions, or for :data:`TARGET` - all a build asks
        for when no rated answer can be graded. Nothing to draft from, or AI
        assistance off, costs nothing, because no question would be asked for.

        Raises:
            AuthorizationError: The caller's role may not edit datasets.
            NotFoundError: The agent is not one the caller may see.
        """
        if not ctx.has(Perm.DATASETS_EDIT):
            raise AuthorizationError(
                message="Building a test set creates a dataset, which your role does not allow"
            )
        agent = await AgentRegistryService(self.db).get(ctx, agent_id)
        count = more or TARGET
        request = await self._request(ctx, agent, count)
        try:
            cost = await self.generation.price_for_agent(ctx, request)
        except AiAssistanceDisabledError, BadRequestError:
            return AgentTestSetEstimate(cost_usd=Decimal(0), priced=True, generate=0)
        return AgentTestSetEstimate(
            cost_usd=cost or Decimal(0), priced=cost is not None, generate=request.count
        )

    async def _dataset(self, ctx: AuthContext, agent: Agent) -> tuple[Dataset, bool]:
        """The agent's test set the caller may edit, and whether it was created now."""
        for candidate in await dataset_repo.for_agent(
            self.db, agent.id, organization_id=ctx.organization_id
        ):
            if await resolve_access(
                self.db, ctx, candidate, Perm.DATASETS_EDIT, resource_type=DATASET
            ):
                return candidate, False
        base = f"{agent.name} - test questions"
        for attempt in range(1, _NAME_TRIES + 1):
            name = base if attempt == 1 else f"{base} ({attempt})"
            if await dataset_repo.get_by_name(self.db, name, organization_id=ctx.organization_id):
                continue
            read = await self.datasets.create(
                ctx,
                DatasetCreate(
                    name=name, description=f"Test questions for {agent.name}.", visibility="private"
                ),
                agent_id=agent.id,
            )
            return await self.datasets.get(ctx, read.id, perm=Perm.DATASETS_EDIT), True
        raise BadRequestError(
            message="Every name for this agent's test set is taken. Rename one of them.",
            details={"agent_id": agent.id},
        )

    async def _held_answers(self, ctx: AuthContext, dataset: Dataset) -> set[UUID]:
        """The answers the newest version already holds as cases."""
        version = await dataset_repo.get_version(
            self.db, dataset.id, dataset.latest_version, organization_id=ctx.organization_id
        )
        if version is None:
            return set()
        return await dataset_repo.held_message_ids(
            self.db, version.id, organization_id=ctx.organization_id
        )

    async def _add_rated(
        self, ctx: AuthContext, dataset: Dataset, agent_id: UUID, since: datetime | None
    ) -> AgentTestSetCounts:
        rated = await agent_run_repo.rated_answers(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            since=since,
            limit=CANDIDATES,
            excluding=await self._held_answers(ctx, dataset),
        )
        counts = AgentTestSetCounts(
            rated_good=0, rated_bad=0, skipped=0, from_others=0, generated_requested=0
        )
        if not rated:
            return counts
        kept: dict[UUID, AnswerAs] = {
            answer.message_id: "counter_example" if answer.rated_down else "reference_answer"
            for answer in rated
        }
        # Read until RATED_LIMIT cases are built: an answer in a conversation the
        # caller cannot open is passed over without taking a place.
        version, counts.skipped = await self.datasets.add_from_messages(
            ctx, dataset.id, list(kept), answer_as=kept, with_history=False, limit=RATED_LIMIT
        )
        if version is None:
            return counts
        added = await dataset_repo.list_cases(
            self.db, version.id, organization_id=ctx.organization_id, limit=None
        )
        owners = {answer.conversation_id: answer.conversation_owner for answer in rated}
        for case in added:
            conversation = case.source_conversation_id
            if (
                case.added_in != version.number
                or conversation is None
                or conversation not in owners
            ):
                continue
            if case.counter_example is not None:
                counts.rated_bad += 1
            else:
                counts.rated_good += 1
            if owners[conversation] != ctx.subject_id:
                counts.from_others += 1
        return counts

    async def _profile(self, ctx: AuthContext, agent: Agent | None) -> ModelProfile | None:
        """The model profile an agent answers on: its published spec's, or its draft's."""
        spec = None if agent is None else await self._spec(ctx, agent)
        if spec is None or spec.model_profile_id is None:
            return None
        return await credential_repo.get_profile(
            self.db, spec.model_profile_id, organization_id=ctx.organization_id
        )

    async def _grade(
        self, ctx: AuthContext, dataset: Dataset, agent: Agent, *, created: bool
    ) -> AgentTestSetJudge:
        """Compare with the good answers, avoid the bad ones, on a judge of another model.

        Only a test set created by this build is set up. One that existed is
        graded as it was - its judge, its rubric, its reference switch - and only
        said to share the agent's model when it does.
        """
        if not await AiAssistanceService(self.db).is_enabled(organization_id=ctx.organization_id):
            return _not_independent("ai_off", kept=not created)
        answers_on = await self._profile(ctx, agent)
        if not created:
            return await self._report(
                ctx, DatasetScoring.model_validate(dataset.scoring), answers_on
            )
        if answers_on is None:
            await self._switch_on(ctx, dataset, None)
            return _not_independent("unknown_model")
        other = next(
            (
                profile
                for profile in await credential_repo.list_profiles(
                    self.db, organization_id=ctx.organization_id
                )
                if not _same_model(profile, answers_on)
            ),
            None,
        )
        if other is None or not ctx.has(Perm.AGENTS_PUBLISH):
            # A judge the caller may not publish stays a draft, and a draft grades nothing.
            await self._switch_on(ctx, dataset, None)
            return _not_independent("one_model" if other is None else "cannot_publish")
        judge = await self._create_judge(ctx, dataset, agent, other)
        return AgentTestSetJudge(agent_id=judge, independent=True)

    async def _report(
        self, ctx: AuthContext, scoring: DatasetScoring, answers_on: ModelProfile | None
    ) -> AgentTestSetJudge:
        """Whether grading as the dataset has it runs on another model than the agent's."""
        if not (scoring.judge.enabled or scoring.reference.enabled):
            return _not_independent("judge_off", kept=True)
        judge = (
            await agent_repo.get(
                self.db, scoring.judge.agent_id, organization_id=ctx.organization_id
            )
            if scoring.judge.agent_id is not None
            else await agent_repo.get_system(
                self.db, organization_id=ctx.organization_id, key=JUDGE.key
            )
        )
        judged_on = await self._profile(ctx, judge)
        if judged_on is None or answers_on is None or _same_model(judged_on, answers_on):
            return AgentTestSetJudge(
                agent_id=scoring.judge.agent_id,
                independent=False,
                reason=REASONS["shares_model"],
                reason_code="shares_model",
                kept=True,
            )
        return AgentTestSetJudge(agent_id=scoring.judge.agent_id, independent=True, kept=True)

    async def _create_judge(
        self, ctx: AuthContext, dataset: Dataset, agent: Agent, profile: ModelProfile
    ) -> UUID | None:
        base = f"{agent.name} - grader"
        for attempt in range(1, _NAME_TRIES + 1):
            name = base if attempt == 1 else f"{base} ({attempt})"
            try:
                async with self.db.begin_nested():
                    read = await self.scoring.create_judge(
                        ctx, dataset.id, JudgeCreate(name=name, model_profile_id=profile.id)
                    )
            except AlreadyExistsError:
                continue
            await self._switch_on(ctx, dataset, read.scoring.judge.agent_id)
            return read.scoring.judge.agent_id
        raise BadRequestError(
            message="Every name for this agent's grader is taken. Rename one of them.",
            details={"agent_id": agent.id},
        )

    async def _switch_on(self, ctx: AuthContext, dataset: Dataset, judge_id: UUID | None) -> None:
        """The judge on, with a starting criterion, and the reference compared."""
        await self.db.refresh(dataset)
        scoring = DatasetScoring.model_validate(dataset.scoring)
        scoring.judge.agent_id = judge_id
        scoring.judge.enabled = True
        if not scoring.judge.criteria:
            scoring.judge.criteria = [STARTING_CRITERION]
        scoring.reference.enabled = True
        await self.scoring.set_scoring(ctx, dataset.id, scoring)

    async def _request(self, ctx: AuthContext, agent: Agent, count: int) -> CaseGenerationRequest:
        spec = await self._spec(ctx, agent)
        sources: list[CaseOriginLiteral] = ["agent"]
        if spec is not None and spec.collection_ids:
            sources.append("knowledge")
        return CaseGenerationRequest(
            agent_id=agent.id, sources=sources, count=min(MAX_GENERATED, max(count, len(sources)))
        )

    async def _spec(self, ctx: AuthContext, agent: Agent) -> AgentSpec | None:
        """The published spec, or the draft of an agent never published; `None` for an
        unfinished draft."""
        version = (
            await agent_repo.get_version(
                self.db, agent.current_version_id, organization_id=ctx.organization_id
            )
            if agent.current_version_id is not None
            else None
        )
        try:
            return AgentSpec.model_validate(version.spec if version else agent.draft_spec)
        except ValidationError:
            return None

    async def _write_more(
        self, ctx: AuthContext, dataset_id: UUID, agent: Agent, *, gradable: int, more: int | None
    ) -> tuple[UUID | None, int, GenerationSkipped | None]:
        """Ask the generator for more questions: the generation, how many, or why not."""
        count = more or max(TARGET - gradable, 0)
        if count == 0:
            return None, 0, "enough"
        request = await self._request(ctx, agent, count)
        try:
            async with self.db.begin_nested():
                started = await self.generation.start(ctx, dataset_id, request, auto_accept=True)
        except AiAssistanceDisabledError:
            return None, 0, "ai_off"
        except SystemAgentUnavailableError:
            return None, 0, "unavailable"
        except BadRequestError:
            return None, 0, "nothing_to_draft"
        return started.id, request.count, None
