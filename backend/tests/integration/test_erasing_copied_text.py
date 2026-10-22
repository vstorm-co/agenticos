"""Erasing a person removes their words from what was copied out of their conversations.

A dataset case, the authoring assistant's evidence and a knowledge-gap draft each
hold text taken from a conversation, and outlive it on purpose. When the person
it was taken from is erased, that text goes - every copy of it - while the rows,
and everybody else's words in them, stay.

Against a real database, because the copies sit in JSONB documents and in
revisions only older versions hold, which only real rows can show reached.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import AuthoringRequest, SpecProposalBatch, SpecProposalHunk
from app.db.models.case_score import CaseScore
from app.db.models.context import ContextFile
from app.db.models.context_proposal import ContextProposal
from app.db.models.conversation import Conversation, Message
from app.db.models.dataset import DatasetCase, DatasetVersion
from app.db.models.eval_run import ArmRole, ArmSource, EvalRun, EvalRunArm, EvalRunCase
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import KnowledgeGapMember, KnowledgeGapTopic, KnowledgeSearch
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.skill_proposal import SkillProposal
from app.repositories import case_score_repo, eval_run_repo, user_repo
from app.schemas.dataset import DatasetCaseCreate, DatasetCaseUpdate, DatasetCreate
from app.services.dataset import DatasetService
from app.services.personal_data import ANONYMISED_CASE_INPUT, PersonalDataService

pytestmark = pytest.mark.anyio

MARKER = "Kowalski-7731"
"""In everything the erased person said, so a search for it finds any copy left."""

_TABLES = (
    "dataset_cases",
    "eval_run_cases",
    "case_scores",
    "spec_proposal_hunks",
    "skill_proposals",
    "context_proposals",
    "authoring_requests",
    "knowledge_gap_topics",
)


class _World:
    """An organization where the person and a colleague each asked an agent once,
    the person rated the colleague's answer down with a comment, and their words
    were then copied into datasets, eval results, proposals and a gap draft."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build(self) -> None:
        db = self.db
        owner = await user_repo.create(db, email=f"o-{uuid4().hex[:8]}@x.io", hashed_password="x")
        self.person = await user_repo.create(
            db, email=f"p-{uuid4().hex[:8]}@x.io", hashed_password="x"
        )
        self.colleague = await user_repo.create(
            db, email=f"c-{uuid4().hex[:8]}@x.io", hashed_password="x"
        )
        org = Organization(id=uuid4(), name="Acme", slug=f"a-{uuid4().hex[:8]}")
        org.created_by_user_id = owner.id
        db.add(org)
        await db.flush()
        db.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
        self.ctx = AuthContext(
            user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER.value
        )
        self.agent = Agent(
            organization_id=org.id, slug=f"clerk-{uuid4().hex[:8]}", name="Clerk", draft_spec={}
        )
        db.add(self.agent)
        await db.flush()

        self.their_conversation, self.their_run, their_answer = await self._asked(
            self.person.id, f"My account {MARKER} was charged twice"
        )
        _, self.colleagues_run, colleagues_answer = await self._asked(
            self.colleague.id, "Where is the parking?"
        )
        db.add(
            MessageRating(
                message_id=colleagues_answer.id,
                user_id=self.person.id,
                rating=-1,
                comment=f"Wrong floor, ask {MARKER}",
            )
        )
        await db.flush()

        await self._cases()
        await self._eval_results()
        await self._proposals()
        await self._gaps()

    async def _asked(self, user_id: UUID, question: str) -> tuple[Conversation, AgentRun, Message]:
        conversation = Conversation(
            user_id=user_id, organization_id=self.ctx.organization_id, title="Help"
        )
        self.db.add(conversation)
        await self.db.flush()
        run = AgentRun(
            organization_id=self.ctx.organization_id,
            agent_id=self.agent.id,
            user_id=user_id,
            conversation_id=conversation.id,
            status="completed",
        )
        self.db.add(run)
        await self.db.flush()
        answer = None
        for ordinal, (role, content) in enumerate(
            (("user", question), ("assistant", f"Here is what I found about: {question}"))
        ):
            answer = Message(
                conversation_id=conversation.id,
                run_id=run.id,
                role=role,
                content=content,
                ordinal=ordinal,
            )
            self.db.add(answer)
            await self.db.flush()
        assert answer is not None
        return conversation, run, answer

    async def _sourced(self, content: DatasetCaseCreate, **links: UUID) -> UUID:
        case = await self.datasets.add_case(self.ctx, self.dataset_id, content)
        revision = await self.db.get(DatasetCase, case.id)
        assert revision is not None
        for field, value in links.items():
            setattr(revision, field, value)
        revision.source = "conversation"
        await self.db.flush()
        return case.case_id

    async def _cases(self) -> None:
        self.datasets = DatasetService(self.db)
        dataset = await self.datasets.create(self.ctx, DatasetCreate(name="billing"))
        self.dataset_id = dataset.id
        self.their_case = await self._sourced(
            DatasetCaseCreate(
                input=f"My account {MARKER} was charged twice",
                history=[{"role": "user", "content": f"Hi, {MARKER} here"}],
                reference_answer=f"Refunding {MARKER}",
                counter_example=f"Ignore {MARKER}",
                note=f"Wrong, says {MARKER}",
                checks=[{"type": "contains", "value": "refund"}],
            ),
            source_conversation_id=self.their_conversation.id,
            source_run_id=self.their_run.id,
        )
        # An edit, so the person's words are in a revision only version 1 still holds.
        await self.datasets.update_case(
            self.ctx,
            self.dataset_id,
            self.their_case,
            DatasetCaseUpdate(input=f"My account {MARKER} was charged three times"),
        )
        self.rated_case = await self._sourced(
            DatasetCaseCreate(
                input="Where is the parking?",
                reference_answer="Level -2",
                note=f"Wrong floor, ask {MARKER}",
            ),
            source_run_id=self.colleagues_run.id,
        )
        self.others_case = await self._sourced(
            DatasetCaseCreate(
                input="Where is the parking?", reference_answer="Level -2", note="Too slow"
            ),
            source_run_id=self.colleagues_run.id,
        )

    async def _revisions(self, case_id: UUID) -> list[DatasetCase]:
        result = await self.db.execute(
            select(DatasetCase).where(DatasetCase.case_id == case_id).order_by(DatasetCase.added_in)
        )
        return list(result.scalars().all())

    async def _eval_results(self) -> None:
        version = (
            (
                await self.db.execute(
                    select(DatasetVersion)
                    .where(DatasetVersion.dataset_id == self.dataset_id)
                    .order_by(DatasetVersion.number.desc())
                )
            )
            .scalars()
            .first()
        )
        assert version is not None
        run = EvalRun(
            agent_id=self.agent.id,
            dataset_id=self.dataset_id,
            dataset_version_id=version.id,
            status="completed",
            scoring={},
            scoring_hash="s",
            estimate_usd=Decimal("1"),
        )
        arm = EvalRunArm(
            role=ArmRole.CANDIDATE.value,
            position=0,
            source=ArmSource.DRAFT.value,
            spec={},
            spec_hash="d",
            model_label="m",
        )
        run = await eval_run_repo.create(
            self.db, organization_id=self.ctx.organization_id, run=run, arms=[arm]
        )
        revisions = [
            *await self._revisions(self.their_case),
            *await self._revisions(self.rated_case),
        ]
        await eval_run_repo.add_cases(
            self.db,
            organization_id=self.ctx.organization_id,
            cases=[
                EvalRunCase(
                    eval_run_id=run.id,
                    arm_id=arm.id,
                    case_id=revision.case_id,
                    case_revision_id=revision.id,
                    position=index,
                    # The two revisions of one case, as two runs over versions 1 and 2 would.
                    attempt=index,
                    answer=f"Answering {revision.input}",
                    calls=[{"tool": "lookup", "args": {"q": revision.input}}],
                )
                for index, revision in enumerate(revisions)
            ],
        )
        for revision in revisions:
            await case_score_repo.create(
                self.db,
                organization_id=self.ctx.organization_id,
                dataset_id=self.dataset_id,
                case_revision_id=revision.id,
                case_id=revision.case_id,
                run_id=None,
                eval_run_id=run.id,
                answer=f"Answering {revision.input}",
                scoring={},
                results=[{"scorer": "judge", "reason": f"It said {revision.input}"}],
                judge=None,
                passed=True,
                review_state="none",
                created_by_user_id=None,
            )

    def _evidence(self) -> list[dict[str, str]]:
        return [
            {"run_id": str(self.their_run.id), "quote": f"My account {MARKER}"},
            {"run_id": str(self.colleagues_run.id), "quote": "Where is the parking?"},
            {"run_id": str(self.colleagues_run.id), "quote": f"ask {MARKER} Where is"},
        ]

    async def _proposals(self) -> None:
        org = self.ctx.organization_id
        batch = SpecProposalBatch(
            organization_id=org, agent_id=self.agent.id, source_started_at=datetime.now(UTC)
        )
        self.db.add(batch)
        await self.db.flush()
        context = ContextFile(organization_id=org, name=f"policy-{uuid4().hex[:6]}")
        self.db.add(context)
        await self.db.flush()
        self.hunk = SpecProposalHunk(
            organization_id=org,
            batch_id=batch.id,
            position=0,
            kind="instructions",
            origin="improve",
            evidence=self._evidence(),
        )
        self.skill_proposal = SkillProposal(
            organization_id=org, name="billing", resources={}, evidence=self._evidence()
        )
        self.context_proposal = ContextProposal(
            organization_id=org, context_id=context.id, evidence=self._evidence()
        )
        self.request = AuthoringRequest(
            organization_id=org,
            kind="verify",
            target="agent",
            agent_id=self.agent.id,
            status="completed",
            estimate_usd=Decimal("0.01"),
            window_days=30,
            report={
                "findings": [{"verdict": "worse", "text": "t", "evidence": self._evidence()}],
                "proposed": 0,
            },
        )
        self.db.add_all([self.hunk, self.skill_proposal, self.context_proposal, self.request])
        await self.db.flush()

    async def _searched(self, kb: KnowledgeBase, run: AgentRun, query: str) -> KnowledgeSearch:
        search = KnowledgeSearch(
            organization_id=self.ctx.organization_id,
            run_id=run.id,
            agent_id=self.agent.id,
            knowledge_base_ids=[kb.id],
            query=query,
            result_count=0,
        )
        self.db.add(search)
        await self.db.flush()
        return search

    async def _topic(self, kb: KnowledgeBase, searches: list[KnowledgeSearch], draft: str):
        topic = KnowledgeGapTopic(
            organization_id=self.ctx.organization_id,
            knowledge_base_id=kb.id,
            centroid=[0.1],
            embedding_model="m",
            draft_title="Parking",
            draft_content=draft,
            draft_sources=[{"kind": "question", "id": str(searches[0].id)}],
            drafted_at=datetime.now(UTC),
        )
        self.db.add(topic)
        await self.db.flush()
        for search in searches:
            self.db.add(KnowledgeGapMember(topic_id=topic.id, search_id=search.id))
        await self.db.flush()
        return topic

    async def _gaps(self) -> None:
        kb = KnowledgeBase(
            organization_id=self.ctx.organization_id,
            name="handbook",
            collection_name=f"handbook_{uuid4().hex[:8]}",
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            scope="org",
            visibility="org",
        )
        self.db.add(kb)
        await self.db.flush()
        theirs = await self._searched(kb, self.their_run, f"charged twice {MARKER}")
        colleagues = await self._searched(kb, self.colleagues_run, "parking level")
        another = await self._searched(kb, self.colleagues_run, "parking hours")
        self.shared_topic = await self._topic(
            kb, [colleagues, theirs], f"People like {MARKER} ask where to park"
        )
        self.others_topic = await self._topic(kb, [another], "Parking opens at 7")


async def _copies_of_marker(db: AsyncSession) -> dict[str, int]:
    counts = {}
    for table in _TABLES:
        counts[table] = (
            await db.execute(
                text(f"SELECT count(*) FROM {table} AS t WHERE t::text LIKE :marker"),  # noqa: S608
                {"marker": f"%{MARKER}%"},
            )
        ).scalar_one()
    return counts


@pytest.fixture
async def world(db) -> _World:
    built = _World(db)
    await built.build()
    return built


class TestTheirWordsGo:
    async def test_no_copy_of_anything_they_said_is_left(self, db, world) -> None:
        assert any(await _copies_of_marker(db))

        await PersonalDataService(db).purge(world.person.id)

        assert await _copies_of_marker(db) == dict.fromkeys(_TABLES, 0)

    async def test_a_case_from_their_conversation_is_anonymised_in_every_version(
        self, db, world
    ) -> None:
        await PersonalDataService(db).purge(world.person.id)

        revisions = await world._revisions(world.their_case)
        assert len(revisions) == 2
        for revision in revisions:
            await db.refresh(revision)
            assert revision.input == ANONYMISED_CASE_INPUT
            assert revision.history == []
            assert revision.reference_answer is None
            assert revision.counter_example is None
            assert revision.note is None
            assert revision.anonymised_at is not None
            # The curator's part stays, and so does the case.
            assert revision.checks == [{"type": "contains", "value": "refund"}]
            assert revision.source_conversation_id is None

    async def test_what_an_eval_recorded_answering_it_goes_and_the_outcome_stays(
        self, db, world
    ) -> None:
        await PersonalDataService(db).purge(world.person.id)

        [revision, *_] = await world._revisions(world.their_case)
        attempt = (
            await db.execute(select(EvalRunCase).where(EvalRunCase.case_revision_id == revision.id))
        ).scalar_one()
        score = (
            await db.execute(select(CaseScore).where(CaseScore.case_revision_id == revision.id))
        ).scalar_one()
        await db.refresh(attempt)
        await db.refresh(score)
        assert (attempt.answer, attempt.calls) == (None, [])
        assert score.answer is None
        assert score.results[0]["reason"] == ""
        assert score.passed is True

    async def test_a_case_from_an_answer_they_only_rated_keeps_the_question(
        self, db, world
    ) -> None:
        """The question and the answer are the colleague's; only the comment was theirs."""
        await PersonalDataService(db).purge(world.person.id)

        [rated] = await world._revisions(world.rated_case)
        await db.refresh(rated)
        assert rated.input == "Where is the parking?"
        assert rated.reference_answer == "Level -2"
        assert rated.note is None
        assert rated.anonymised_at is None
        assert rated.source_run_id == world.colleagues_run.id

    async def test_their_quotes_go_from_every_proposal_and_report(self, db, world) -> None:
        await PersonalDataService(db).purge(world.person.id)

        kept = [{"run_id": str(world.colleagues_run.id), "quote": "Where is the parking?"}]
        for row in (world.hunk, world.skill_proposal, world.context_proposal, world.request):
            await db.refresh(row)
        assert world.hunk.evidence == kept
        assert world.skill_proposal.evidence == kept
        assert world.context_proposal.evidence == kept
        assert world.request.report is not None
        assert world.request.report["findings"][0]["evidence"] == kept
        assert world.request.report["proposed"] == 0

    async def test_a_topic_they_asked_into_loses_its_draft_and_others_keep_theirs(
        self, db, world
    ) -> None:
        await PersonalDataService(db).purge(world.person.id)

        await db.refresh(world.shared_topic)
        await db.refresh(world.others_topic)
        assert world.shared_topic.draft_content is None
        assert world.shared_topic.draft_title is None
        assert world.shared_topic.draft_sources == []
        assert world.shared_topic.drafted_at is None
        assert world.others_topic.draft_content == "Parking opens at 7"


class TestEverybodyElsesStays:
    async def test_cases_of_other_people_are_untouched(self, db, world) -> None:
        await PersonalDataService(db).purge(world.person.id)

        [others] = await world._revisions(world.others_case)
        await db.refresh(others)
        assert (others.input, others.reference_answer, others.note) == (
            "Where is the parking?",
            "Level -2",
            "Too slow",
        )
        [revision] = await world._revisions(world.rated_case)
        attempt = (
            await db.execute(select(EvalRunCase).where(EvalRunCase.case_revision_id == revision.id))
        ).scalar_one()
        await db.refresh(attempt)
        assert attempt.answer == "Answering Where is the parking?"

    async def test_erasing_the_colleague_leaves_the_persons_own_case_and_quotes(
        self, db, world
    ) -> None:
        await PersonalDataService(db).purge(world.colleague.id)

        for revision in await world._revisions(world.their_case):
            await db.refresh(revision)
            assert MARKER in revision.input
            assert revision.anonymised_at is None
        await db.refresh(world.hunk)
        assert [item["run_id"] for item in world.hunk.evidence] == [str(world.their_run.id)]


class TestPurgingTwice:
    async def test_the_second_purge_finds_nothing_left_to_do(self, db, world) -> None:
        first = await PersonalDataService(db).purge(world.person.id)
        second = await PersonalDataService(db).purge(world.person.id)

        assert first.anonymised_cases == 2
        assert first.case_copies == 4
        assert first.case_notes == 1
        assert first.evidence_quotes == 8
        assert first.gap_drafts == 1
        assert second.model_dump() == dict.fromkeys(second.model_dump(), 0)
