"""Erasing a person removes their words from what was copied out of their conversations.

A dataset case, the authoring assistant's evidence and a knowledge-gap draft each
hold text taken from a conversation, and outlive it on purpose. When the person
it was taken from is erased, that text goes - every copy of it - while the rows,
and everybody else's words in them, stay.

Against a real database, because the copies sit in JSONB documents and in
revisions only older versions hold, which only real rows can show reached.
"""

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext, OrgRoleName
from app.db.locks import LockScope, hold_subject
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import AuthoringRequest, SpecProposalBatch, SpecProposalHunk
from app.db.models.case_generation import CaseGeneration, CaseProposal
from app.db.models.case_score import CaseScore
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.context import ContextFile
from app.db.models.context_proposal import ContextProposal
from app.db.models.conversation import Conversation, Message
from app.db.models.dataset import DatasetCase, DatasetVersion
from app.db.models.eval_run import ArmRole, ArmSource, EvalRun, EvalRunArm, EvalRunCase
from app.db.models.intercepted_tool_call import InterceptedToolCall
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import KnowledgeGapMember, KnowledgeGapTopic, KnowledgeSearch
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.run_manifest import RunManifest
from app.db.models.skill_proposal import SkillProposal
from app.db.models.user import User
from app.repositories import case_score_repo, eval_run_repo, personal_data_repo, user_repo
from app.schemas.dataset import (
    DatasetCaseCreate,
    DatasetCaseFromMessage,
    DatasetCaseRead,
    DatasetCaseUpdate,
    DatasetCreate,
)
from app.services.dataset import DatasetService
from app.services.personal_data import ANONYMISED_CASE_INPUT, PersonalDataService
from app.services.user import UserService

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

        self.their_conversation, self.their_run, self.their_answer = await self._asked(
            self.person.id, f"My account {MARKER} was charged twice"
        )
        (
            self.colleagues_conversation,
            self.colleagues_run,
            self.colleagues_answer,
        ) = await self._asked(self.colleague.id, "Where is the parking?")
        db.add(
            MessageRating(
                message_id=self.colleagues_answer.id,
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
            {"run_id": str(self.colleagues_run.id), "quote": f"floor, ask {MARKER} Where is"},
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


async def _channel_thread(world: _World) -> tuple[Conversation, AgentRun]:
    """A Slack thread the person opened, where the colleague then asked the agent something."""
    db = world.db
    identities = {}
    for person in (world.person, world.colleague):
        identities[person.id] = ChannelIdentity(
            platform="slack", platform_user_id=uuid4().hex[:10], user_id=person.id
        )
        db.add(identities[person.id])
    await db.flush()
    thread = Conversation(
        user_id=world.person.id, organization_id=world.ctx.organization_id, title="#help"
    )
    db.add(thread)
    await db.flush()
    run = AgentRun(
        organization_id=world.ctx.organization_id,
        agent_id=world.agent.id,
        user_id=world.colleague.id,
        conversation_id=thread.id,
        channel_identity_id=identities[world.colleague.id].id,
        status="completed",
    )
    db.add(run)
    await db.flush()
    for ordinal, (role, content, speaker) in enumerate(
        (
            ("user", f"Is {MARKER} on call?", world.person.id),
            ("assistant", "Yes.", None),
            ("user", "Where is the parking?", world.colleague.id),
            ("assistant", "Level -2", None),
        )
    ):
        db.add(
            Message(
                conversation_id=thread.id,
                run_id=run.id if ordinal >= 2 else None,
                role=role,
                content=content,
                ordinal=ordinal,
                channel_identity_id=identities[speaker].id if speaker else None,
            )
        )
    await db.flush()
    return thread, run


class TestSharedThreads:
    """A channel thread belongs to whoever spoke first, and holds everyone who spoke after."""

    async def test_a_colleagues_case_from_their_channel_thread_keeps_its_question(
        self, db, world
    ) -> None:
        thread, run = await _channel_thread(world)
        case_id = await world._sourced(
            DatasetCaseCreate(
                input="Where is the parking?",
                history=[
                    {"role": "user", "content": f"Is {MARKER} on call?"},
                    {"role": "assistant", "content": "Yes."},
                ],
                reference_answer="Level -2",
            ),
            source_conversation_id=thread.id,
            source_run_id=run.id,
        )

        purged = await PersonalDataService(db).purge(world.person.id)

        [case] = await world._revisions(case_id)
        await db.refresh(case)
        assert purged.history_turns == 1
        assert case.input == "Where is the parking?"
        assert case.reference_answer == "Level -2"
        assert case.anonymised_at is None
        assert case.history == [
            {"role": "user", "content": ANONYMISED_CASE_INPUT},
            {"role": "assistant", "content": ANONYMISED_CASE_INPUT},
        ]

    async def test_a_case_a_chat_account_of_theirs_asked_is_anonymised(self, db, world) -> None:
        thread, _ = await _channel_thread(world)
        identity = (
            await db.execute(
                select(ChannelIdentity).where(ChannelIdentity.user_id == world.person.id)
            )
        ).scalar_one()
        run = AgentRun(
            organization_id=world.ctx.organization_id,
            agent_id=world.agent.id,
            user_id=world.ctx.user_id,
            initiated_by_publisher_fallback=True,
            conversation_id=thread.id,
            channel_identity_id=identity.id,
            status="completed",
        )
        db.add(run)
        await db.flush()
        case_id = await world._sourced(
            DatasetCaseCreate(input=f"Is {MARKER} on call?", reference_answer="Yes."),
            source_run_id=run.id,
        )

        await PersonalDataService(db).purge(world.person.id)

        [case] = await world._revisions(case_id)
        await db.refresh(case)
        assert case.input == ANONYMISED_CASE_INPUT
        assert case.anonymised_at is not None


class TestTheirComments:
    async def test_a_note_a_curator_wrote_around_their_comment_goes(self, db, world) -> None:
        [rated] = await world._revisions(world.rated_case)
        rated.note = f"Reader said: Wrong floor, ask {MARKER} - check the map"
        await db.flush()

        await PersonalDataService(db).purge(world.person.id)

        await db.refresh(rated)
        assert rated.note is None

    async def test_a_note_quoting_their_comment_with_its_punctuation_goes(self, db, world) -> None:
        [rated] = await world._revisions(world.rated_case)
        rated.note = f'"wrong floor, ask {MARKER}." - flagged by support'
        await db.flush()

        await PersonalDataService(db).purge(world.person.id)

        await db.refresh(rated)
        assert rated.note is None

    async def test_a_note_that_only_shares_letters_with_their_comment_stays(
        self, db, world
    ) -> None:
        _, run, answer = await world._asked(world.colleague.id, "Can I park here?")
        db.add(
            MessageRating(message_id=answer.id, user_id=world.person.id, rating=-1, comment="bad")
        )
        await db.flush()
        case_id = await world._sourced(
            DatasetCaseCreate(input="Can I park here?", reference_answer="No", note="badly worded"),
            source_run_id=run.id,
        )

        await PersonalDataService(db).purge(world.person.id)

        [case] = await world._revisions(case_id)
        await db.refresh(case)
        assert case.note == "badly worded"

    async def test_a_drafted_case_loses_their_comment_and_keeps_the_question(
        self, db, world
    ) -> None:
        generation = CaseGeneration(
            organization_id=world.ctx.organization_id,
            dataset_id=world.dataset_id,
            sources=["conversations"],
            requested_count=1,
        )
        db.add(generation)
        await db.flush()
        draft = CaseProposal(
            organization_id=world.ctx.organization_id,
            generation_id=generation.id,
            dataset_id=world.dataset_id,
            position=0,
            origin="conversation",
            input="Where is the parking?",
            note=f"Wrong floor, ask {MARKER}",
            source_run_id=world.colleagues_run.id,
        )
        db.add(draft)
        await db.flush()

        await PersonalDataService(db).purge(world.person.id)

        await db.refresh(draft)
        assert (draft.input, draft.note) == ("Where is the parking?", None)


class TestAfterTheErasure:
    async def test_editing_an_anonymised_case_without_its_question_keeps_it_marked(
        self, db, world
    ) -> None:
        await PersonalDataService(db).purge(world.person.id)

        edited = await world.datasets.update_case(
            world.ctx, world.dataset_id, world.their_case, DatasetCaseUpdate(tags=["billing"])
        )
        rewritten = await world.datasets.update_case(
            world.ctx,
            world.dataset_id,
            world.their_case,
            DatasetCaseUpdate(input="Why was I charged twice?", reference_answer="A refund"),
        )

        assert edited.anonymised_at is not None
        assert rewritten.anonymised_at is None


async def _from_answer(world: _World, answer_id: UUID, **kwargs) -> DatasetCase:
    """A case an owner added with Add to dataset, the way the product adds one."""
    added = await world.datasets.add_from_message(
        world.ctx,
        world.dataset_id,
        DatasetCaseFromMessage(message_id=answer_id),
        **kwargs,
    )
    revision = await world.db.get(DatasetCase, added.id)
    assert revision is not None
    return revision


async def _thread_deleted(world: _World, conversation: Conversation) -> None:
    """What deleting a conversation does to the cases taken from it, and the thread itself."""
    await personal_data_repo.unlink_dataset_cases_from_conversation(
        world.db, conversation.id, organization_id=world.ctx.organization_id
    )
    await world.db.delete(conversation)
    await world.db.flush()


class TestWhenTheSourceIsGone:
    """The case records whose words it holds, so an erasure finds it after the thread goes."""

    async def test_a_case_from_a_thread_deleted_first_is_still_anonymised(self, db, world) -> None:
        case = await _from_answer(world, world.their_answer.id)
        assert case.asked_by_user_id == world.person.id
        await _thread_deleted(world, world.their_conversation)
        await db.delete(world.their_run)
        await db.flush()

        await PersonalDataService(db).purge(world.person.id)

        await db.refresh(case)
        assert case.source_conversation_id is None
        assert case.input == ANONYMISED_CASE_INPUT
        assert case.anonymised_at is not None

    async def test_their_comment_kept_as_a_note_goes_after_the_rating_does(self, db, world) -> None:
        case = await _from_answer(world, world.colleagues_answer.id)
        assert (case.note, case.noted_by_user_id) == (f"Wrong floor, ask {MARKER}", world.person.id)
        await _thread_deleted(world, world.colleagues_conversation)

        await PersonalDataService(db).purge(world.person.id)

        await db.refresh(case)
        assert (case.input, case.note, case.anonymised_at) == ("Where is the parking?", None, None)

    async def test_their_turn_in_a_colleagues_case_goes_after_the_channel_thread_does(
        self, db, world
    ) -> None:
        thread, run = await _channel_thread(world)
        answer = (
            await db.execute(
                select(Message).where(Message.conversation_id == thread.id, Message.ordinal == 3)
            )
        ).scalar_one()
        case = await _from_answer(world, answer.id)
        assert case.asked_by_user_id == world.colleague.id
        assert case.history_author_ids == [world.person.id, None]
        await _thread_deleted(world, thread)

        await PersonalDataService(db).purge(world.person.id)

        await db.refresh(case)
        assert case.input == "Where is the parking?"
        assert case.history == [
            {"role": "user", "content": ANONYMISED_CASE_INPUT},
            {"role": "assistant", "content": ANONYMISED_CASE_INPUT},
        ]
        assert case.history_author_ids == [None, None]

    async def test_deleting_their_account_anonymises_what_they_asked(self, db, world) -> None:
        case = await _from_answer(world, world.their_answer.id)

        await UserService(db).delete(world.person.id)

        await db.refresh(case)
        assert case.input == ANONYMISED_CASE_INPUT
        assert case.asked_by_user_id is None


class TestInEveryOrganization:
    async def test_their_cases_go_in_every_organization_and_nobody_elses_do(
        self, db, world
    ) -> None:
        other = Organization(
            id=uuid4(),
            name="Globex",
            slug=f"g-{uuid4().hex[:8]}",
            created_by_user_id=world.colleague.id,
        )
        db.add(other)
        await db.flush()
        for person, role in ((world.colleague, "owner"), (world.person, "member")):
            db.add(OrganizationMember(organization_id=other.id, user_id=person.id, role=role))
        await db.flush()
        globex = AuthContext(
            user_id=world.colleague.id, organization_id=other.id, role=OrgRoleName.OWNER.value
        )
        datasets = DatasetService(db)
        dataset = await datasets.create(globex, DatasetCreate(name="globex"))
        theirs = await datasets.add_case(
            globex, dataset.id, DatasetCaseCreate(input=f"{MARKER} asks", reference_answer="a")
        )
        colleagues = await datasets.add_case(
            globex, dataset.id, DatasetCaseCreate(input="Colleague asks", reference_answer="b")
        )
        for case_id, asker in ((theirs.id, world.person.id), (colleagues.id, world.colleague.id)):
            row = await db.get(DatasetCase, case_id)
            assert row is not None
            row.asked_by_user_id = asker
        await db.flush()
        ours = await _from_answer(world, world.their_answer.id)

        await PersonalDataService(db).purge(world.person.id)

        for case_id, expected in (
            (theirs.id, ANONYMISED_CASE_INPUT),
            (colleagues.id, "Colleague asks"),
            (ours.id, ANONYMISED_CASE_INPUT),
        ):
            row = await db.get(DatasetCase, case_id)
            assert row is not None
            await db.refresh(row)
            assert row.input == expected


class TestAuthorshipStaysInside:
    async def test_whose_words_a_case_holds_is_never_read_out(self, db, world) -> None:
        case = await _from_answer(world, world.their_answer.id)

        read = DatasetCaseRead.model_validate(case).model_dump()
        exported = await world.datasets.export(
            world.ctx, world.dataset_id, version=None, fmt="jsonl"
        )

        for field in ("asked_by_user_id", "history_author_ids", "noted_by_user_id"):
            assert field not in read
        assert str(world.person.id) not in exported.content

    async def test_a_history_and_its_authors_cannot_drift_apart(self, db, world) -> None:
        [revision, *_] = await world._revisions(world.their_case)
        revision.history_author_ids = []

        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.flush()

    async def test_an_edited_history_keeps_who_wrote_the_turns_it_kept(self, db, world) -> None:
        thread, _ = await _channel_thread(world)
        answer = (
            await db.execute(
                select(Message).where(Message.conversation_id == thread.id, Message.ordinal == 3)
            )
        ).scalar_one()
        case = await _from_answer(world, answer.id)

        edited = await world.datasets.update_case(
            world.ctx,
            world.dataset_id,
            case.case_id,
            DatasetCaseUpdate(
                history=[
                    {"role": "user", "content": "Context the curator added"},
                    *case.history,
                ]
            ),
        )

        revision = await db.get(DatasetCase, edited.id)
        assert revision is not None
        assert revision.history_author_ids == [None, world.person.id, None]
        assert revision.asked_by_user_id == world.colleague.id

    async def test_a_turn_the_curator_touched_up_stays_its_writers(self, db, world) -> None:
        thread, _ = await _channel_thread(world)
        answer = (
            await db.execute(
                select(Message).where(Message.conversation_id == thread.id, Message.ordinal == 3)
            )
        ).scalar_one()
        case = await _from_answer(world, answer.id)

        edited = await world.datasets.update_case(
            world.ctx,
            world.dataset_id,
            case.case_id,
            DatasetCaseUpdate(
                history=[
                    {"role": "user", "content": f"Is {MARKER} on call today?"},
                    {"role": "assistant", "content": "Yes."},
                ]
            ),
        )

        revision = await db.get(DatasetCase, edited.id)
        assert revision is not None
        assert revision.history_author_ids == [world.person.id, None]


def _migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0177_dataset_case_anonymised_at.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0177", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheBackfill:
    """Cases written before authorship was kept get it from the links they still hold."""

    async def _forgotten(self, db: AsyncSession, case: DatasetCase) -> None:
        await db.execute(
            text(
                "UPDATE dataset_cases SET asked_by_user_id = NULL, noted_by_user_id = NULL, "
                "history_author_ids = array_fill(NULL::uuid, ARRAY[jsonb_array_length(history)]) "
                "WHERE id = :id"
            ),
            {"id": case.id},
        )

    async def _backfill(self, db: AsyncSession) -> None:
        migration = _migration()
        await db.run_sync(
            lambda session: [
                step(session.connection())
                for step in (migration._asked_by, migration._history_authors, migration._noted_by)
            ]
        )

    async def test_who_asked_wrote_and_commented_comes_back_from_the_thread(
        self, db, world
    ) -> None:
        thread, _ = await _channel_thread(world)
        answer = (
            await db.execute(
                select(Message).where(Message.conversation_id == thread.id, Message.ordinal == 3)
            )
        ).scalar_one()
        shared = await _from_answer(world, answer.id)
        noted = await _from_answer(world, world.colleagues_answer.id)
        for case in (shared, noted):
            await self._forgotten(db, case)

        await self._backfill(db)

        for case in (shared, noted):
            await db.refresh(case)
        assert shared.asked_by_user_id == world.colleague.id
        assert shared.history_author_ids == [world.person.id, None]
        assert noted.noted_by_user_id == world.person.id

    async def test_a_turn_said_twice_in_its_thread_is_left_without_an_author(
        self, db, world
    ) -> None:
        thread, _ = await _channel_thread(world)
        db.add(
            Message(
                conversation_id=thread.id,
                role="user",
                content=f"Is {MARKER} on call?",
                ordinal=4,
                author_user_id=world.colleague.id,
            )
        )
        await db.flush()
        answer = (
            await db.execute(
                select(Message).where(Message.conversation_id == thread.id, Message.ordinal == 3)
            )
        ).scalar_one()
        case = await _from_answer(world, answer.id)
        await self._forgotten(db, case)

        await self._backfill(db)

        await db.refresh(case)
        assert case.history_author_ids == [None, None]


class TestWhatAnEvalRunKept:
    async def test_the_question_goes_from_the_manifests_and_held_calls_of_its_runs(
        self, db, world
    ) -> None:
        """The agent's run was handed the case's question, and the judge's the answer too."""
        org = world.ctx.organization_id
        runs = []
        for _ in range(2):
            run = AgentRun(organization_id=org, agent_id=world.agent.id, status="completed")
            db.add(run)
            await db.flush()
            db.add(
                RunManifest(
                    run_id=run.id,
                    organization_id=org,
                    payload={"instructions": "Be brief.", "messages": [{"content": MARKER}]},
                )
            )
            runs.append(run)
        answering, judging = runs
        db.add(
            InterceptedToolCall(
                organization_id=org,
                run_id=answering.id,
                sequence=0,
                tool_call_id="call-0",
                tool_name="refund",
                tool_id="tool:refund",
                args={"account": MARKER},
                outcome="blocked",
                reason="writes",
            )
        )
        [revision, *_] = await world._revisions(world.their_case)
        attempt = (
            await db.execute(select(EvalRunCase).where(EvalRunCase.case_revision_id == revision.id))
        ).scalar_one()
        attempt.agent_run_id = answering.id
        score = (
            await db.execute(select(CaseScore).where(CaseScore.case_revision_id == revision.id))
        ).scalar_one()
        score.results = [{**score.results[0], "judge_run_id": str(judging.id)}]
        await db.flush()

        await PersonalDataService(db).purge(world.person.id)

        kept = (
            await db.execute(
                select(RunManifest).where(RunManifest.run_id.in_([answering.id, judging.id]))
            )
        ).scalars()
        for manifest in kept:
            await db.refresh(manifest)
            assert (manifest.payload, manifest.truncated) == ({"instructions": "Be brief."}, True)
        held = (
            await db.execute(
                select(InterceptedToolCall).where(InterceptedToolCall.run_id == answering.id)
            )
        ).scalar_one()
        await db.refresh(held)
        assert held.args == {}
        assert await db.get(AgentRun, answering.id) is not None


class TestRunsOfALinkedChatAccount:
    async def test_a_search_a_chat_account_of_theirs_asked_goes_with_them(self, db, world) -> None:
        identity = ChannelIdentity(
            platform="slack", platform_user_id=uuid4().hex[:10], user_id=world.person.id
        )
        db.add(identity)
        await db.flush()
        run = AgentRun(
            organization_id=world.ctx.organization_id,
            agent_id=world.agent.id,
            user_id=world.ctx.user_id,
            initiated_by_publisher_fallback=True,
            channel_identity_id=identity.id,
            status="completed",
        )
        db.add(run)
        await db.flush()
        kb = (await db.execute(select(KnowledgeBase))).scalars().first()
        assert kb is not None
        search = await world._searched(kb, run, f"{MARKER} parking")

        await PersonalDataService(db).purge(world.person.id)

        assert await db.get(KnowledgeSearch, search.id) is None
        assert await personal_data_repo.askers_of(db, [run.id]) == set()


class TestCopiesOfACaseThatLostATurn:
    async def test_what_an_eval_kept_of_a_colleagues_case_holding_their_turn_goes(
        self, db, world
    ) -> None:
        thread, _ = await _channel_thread(world)
        answer = (
            await db.execute(
                select(Message).where(Message.conversation_id == thread.id, Message.ordinal == 3)
            )
        ).scalar_one()
        case = await _from_answer(world, answer.id)
        arm = (await db.execute(select(EvalRunArm))).scalars().first()
        assert arm is not None
        attempt = EvalRunCase(
            organization_id=world.ctx.organization_id,
            eval_run_id=arm.eval_run_id,
            arm_id=arm.id,
            case_id=case.case_id,
            case_revision_id=case.id,
            position=99,
            answer=f"Answering whether {MARKER} is on call",
            calls=[{"tool": "roster", "args": {"who": MARKER}}],
        )
        db.add(attempt)
        await db.flush()

        await PersonalDataService(db).purge(world.person.id)

        await db.refresh(attempt)
        assert (attempt.answer, attempt.calls) == (None, [])


class TestTheirScoredAnswers:
    async def test_an_answer_a_chat_account_of_theirs_got_is_cleared_from_its_score(
        self, db, world
    ) -> None:
        identity = ChannelIdentity(
            platform="slack", platform_user_id=uuid4().hex[:10], user_id=world.person.id
        )
        db.add(identity)
        await db.flush()
        run = AgentRun(
            organization_id=world.ctx.organization_id,
            agent_id=world.agent.id,
            user_id=world.ctx.user_id,
            initiated_by_publisher_fallback=True,
            channel_identity_id=identity.id,
            status="completed",
        )
        db.add(run)
        await db.flush()
        [revision] = await world._revisions(world.others_case)
        score = await case_score_repo.create(
            db,
            organization_id=world.ctx.organization_id,
            dataset_id=world.dataset_id,
            case_revision_id=revision.id,
            case_id=revision.case_id,
            run_id=run.id,
            eval_run_id=None,
            answer=f"Here you go, {MARKER}",
            scoring={},
            results=[],
            judge=None,
            passed=True,
            review_state="none",
            created_by_user_id=None,
        )

        await PersonalDataService(db).purge(world.person.id)

        await db.refresh(score)
        assert score.answer is None


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


class TestWritingWhileTheyAreErased:
    """A writer that read somebody's words before a slow step asks again before writing them."""

    async def _person(self, engine) -> tuple[async_sessionmaker, UUID]:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as setup:
            person = await user_repo.create(
                setup, email=f"p-{uuid4().hex[:8]}@x.io", hashed_password="x"
            )
            await setup.commit()
        return factory, person.id

    async def test_somebody_who_is_here_may_be_quoted(self, engine) -> None:
        factory, person = await self._person(engine)
        async with factory() as session:
            assert await personal_data_repo.present_among(session, [person]) == {person}

    async def test_somebody_being_erased_may_not(self, engine) -> None:
        factory, person = await self._person(engine)
        erasing = factory()
        try:
            await user_repo.get_by_id_for_update(erasing, person)
            await hold_subject(erasing, LockScope.PERSONAL_DATA_PER_USER, person)
            async with factory() as session:
                assert await personal_data_repo.present_among(session, [person]) == set()
        finally:
            await erasing.rollback()
            await erasing.close()

    async def test_somebody_a_note_is_being_written_about_may_still_be(self, engine) -> None:
        """A memory write takes the same lock, and leaves the account's row alone."""
        factory, person = await self._person(engine)
        writing = factory()
        try:
            await hold_subject(writing, LockScope.PERSONAL_DATA_PER_USER, person)
            async with factory() as session:
                assert await personal_data_repo.present_among(session, [person]) == {person}
        finally:
            await writing.rollback()
            await writing.close()

    async def test_somebody_whose_account_is_gone_may_not(self, engine) -> None:
        factory, person = await self._person(engine)
        async with factory() as session:
            await session.execute(delete(User).where(User.id == person))
            await session.commit()
        async with factory() as session:
            assert await personal_data_repo.present_among(session, [person]) == set()
