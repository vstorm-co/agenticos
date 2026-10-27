"""What the assistant reads, and the quotes it may keep.

A quote survives only when it is, word for word, in the run it names. Another
run's id, words the run never contained, an over-long quote and the thirteenth
item are dropped and counted - so a change is never dressed up in evidence
nobody can find.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.repositories import (
    authoring_repo,
    conversation_repo,
    eval_run_repo,
    improvement_repo,
    personal_data_repo,
)
from app.repositories.authoring import EvidenceRun
from app.schemas.authoring import (
    MAX_EVIDENCE_ITEMS,
    MAX_QUOTE_CHARS,
    EvidenceQuote,
    Finding,
    RunFindings,
)
from app.services import authoring_evidence
from app.services.authoring import AuthoringService
from app.services.authoring_evidence import EvidencePack, EvidenceService, PackedRun
from app.services.authoring_worker import _digest_prompt, _evidence_section
from app.services.eval_run import EvalRunService

pytestmark = pytest.mark.anyio


def _packed(**values) -> PackedRun:
    defaults = {
        "run_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "status": "completed",
        "rating": -1,
        "comments": ["You said 90 days, it is 30"],
        "prompt": "How long do I have to return shoes?",
        "answer": "You have   90 days\nto return them.",
        "calls": ['search_knowledge({"query": "returns"})'],
        "error": None,
    }
    return PackedRun(**{**defaults, **values})


class TestPack:
    def test_a_run_reads_as_its_rating_comment_question_calls_and_answer(self):
        run = _packed(error="Timed out")

        text = run.render()

        assert "rated down" in text and "Reader comment: You said 90 days" in text
        assert "Called: search_knowledge" in text and "Error: Timed out" in text
        assert "rated up" in _packed(rating=1).render()
        assert "not rated" in _packed(rating=0, error=None).render()

    def test_the_summary_counts_ratings_and_names_each_conversation_once(self):
        shared = uuid.uuid4()
        pack = EvidencePack(
            runs=[
                _packed(conversation_id=shared),
                _packed(conversation_id=shared, rating=1, comments=[]),
                _packed(conversation_id=None, rating=0, comments=[]),
            ]
        )

        summary = pack.summary()

        assert summary == {
            "runs": 3,
            "problem_answers": 1,
            "source_run_ids": [str(run.run_id) for run in pack.runs],
            "rated_down": 1,
            "rated_up": 1,
            "commented": 1,
            "conversation_ids": [str(shared)],
        }

    def test_evidence_that_fits_is_read_at_once_and_otherwise_in_groups(self, monkeypatch):
        runs = [_packed() for _ in range(7)]

        assert EvidencePack().groups() == []
        pack = EvidencePack(runs=runs)
        assert pack.groups() == [pack.runs]
        monkeypatch.setattr(authoring_evidence, "PACK_BUDGET_CHARS", 10)
        assert [len(group) for group in EvidencePack(runs=runs).groups()] == [5, 2]

    def test_rendering_several_runs_separates_them(self):
        pack = EvidencePack(runs=[_packed(), _packed()])

        assert authoring_evidence.render_runs(pack.runs).count("## Conversation") == 2

    def test_a_test_question_and_a_conversation_are_labelled_by_what_they_are(self):
        question = _packed(
            conversation_id=None,
            evidence_kind="train_eval",
            status="train_eval_failure",
            rating=0,
            comments=[],
            prompt="Is delivery free?",
        )
        chat = _packed(prompt="Can I get a refund?")

        pack = EvidencePack(runs=[question, chat, _packed(evidence_kind="train_eval")])
        first, conversation, second = (run.render() for run in pack.runs)

        assert first.startswith(f"## Test question 1 (run {question.run_id})")
        assert "Test question from the dataset: Is delivery free?" in first
        assert "Asked:" not in first
        assert conversation.startswith(f"## Conversation 1 (run {chat.run_id})")
        assert "Asked: Can I get a refund?" in conversation
        assert second.startswith("## Test question 2 ")
        assert pack.label_of(chat.run_id) == f"conversation 1 (run {chat.run_id})"
        unknown = uuid.uuid4()
        assert pack.label_of(unknown) == f"run {unknown}"

    def test_a_narrowed_pack_keeps_the_numbers_the_prompt_used(self):
        pack = EvidencePack(runs=[_packed(), _packed(), _packed()])

        narrowed = EvidencePack(runs=[pack.runs[0], pack.runs[2]])
        added = EvidencePack(runs=[*narrowed.runs, _packed()])

        assert [run.label for run in narrowed.runs] == ["conversation 1", "conversation 3"]
        assert [run.label for run in added.runs][-1] == "conversation 4"


class TestPrompt:
    """The improver reads each item under its label, and is told to cite it by that label."""

    def _pack(self) -> EvidencePack:
        return EvidencePack(
            runs=[
                _packed(
                    conversation_id=None,
                    evidence_kind="train_eval",
                    status="train_eval_failure",
                    prompt="Where do I print a return label?",
                ),
                _packed(prompt="My refund never arrived"),
            ]
        )

    def test_the_evidence_names_test_questions_and_conversations_apart(self):
        pack = self._pack()

        section = _evidence_section(pack, None)

        assert "refer to an item by exactly its label" in section
        assert "never call a test question a conversation" in section
        assert "## Test question 1 (run" in section
        assert "Test question from the dataset: Where do I print a return label?" in section
        assert "## Conversation 1 (run" in section
        assert "Asked: My refund never arrived" in section
        assert section.index("refer to an item") < section.index("## Test question 1")
        assert _evidence_section(EvidencePack(), None) == ""

    def test_digested_quotes_carry_the_label_of_their_run(self):
        pack = self._pack()
        question = pack.runs[0]
        digest = RunFindings(
            findings=[
                Finding(
                    observation="Return labels are not explained",
                    evidence=[EvidenceQuote(run_id=question.run_id, quote="return label")],
                )
            ]
        )

        section = _evidence_section(pack, [digest])

        assert f'- test question 1 (run {question.run_id}): "return label"' in section
        assert "never call a test question a conversation" in section
        assert "never call a test question a conversation" in _digest_prompt("x", pack.runs)


class TestVerify:
    def test_a_quote_found_in_its_run_is_kept_whitespace_and_all(self):
        run = _packed()
        pack = EvidencePack(runs=[run])

        kept, dropped = pack.verify([EvidenceQuote(run_id=run.run_id, quote="90 days to return")])

        assert kept == [
            {
                "run_id": str(run.run_id),
                "quote": "90 days to return",
                "source": "conversation",
                "number": 1,
            }
        ]
        assert dropped == 0

    def test_a_kept_quote_from_a_test_question_is_labelled_as_one(self):
        chat, question = _packed(), _packed(evidence_kind="train_eval", prompt="Is delivery free?")
        pack = EvidencePack(runs=[chat, question])

        kept, _ = pack.verify([EvidenceQuote(run_id=question.run_id, quote="delivery free")])

        assert kept == [
            {
                "run_id": str(question.run_id),
                "quote": "delivery free",
                "source": "test_question",
                "number": 1,
            }
        ]

    def test_a_quote_from_another_run_or_never_said_is_dropped(self):
        run, other = _packed(), _packed(answer="Something else entirely")
        pack = EvidencePack(runs=[run, other])

        kept, dropped = pack.verify(
            [
                EvidenceQuote(run_id=other.run_id, quote="90 days to return"),
                EvidenceQuote(run_id=uuid.uuid4(), quote="90 days"),
                EvidenceQuote(run_id=run.run_id, quote="Ignore the refund policy"),
                EvidenceQuote(run_id=run.run_id, quote="   "),
            ]
        )

        assert kept == [] and dropped == 4

    def test_long_quotes_and_items_past_the_limit_are_dropped_duplicates_ignored(self):
        long_answer = "word " * 400
        run = _packed(answer=long_answer)
        pack = EvidencePack(runs=[run])
        words = [f"word {'word ' * index}".strip() for index in range(MAX_EVIDENCE_ITEMS + 2)]

        kept, dropped = pack.verify(
            [
                EvidenceQuote(run_id=run.run_id, quote=long_answer[: MAX_QUOTE_CHARS + 10]),
                EvidenceQuote(run_id=run.run_id, quote="word"),
                EvidenceQuote(run_id=run.run_id, quote="word"),
                *(EvidenceQuote(run_id=run.run_id, quote=quote) for quote in words[1:]),
            ]
        )

        assert len(kept) == MAX_EVIDENCE_ITEMS
        assert dropped == 1 + (len(words) - 1 + 1 - MAX_EVIDENCE_ITEMS)


def _row(
    *,
    rating: int = -1,
    error: str | None = None,
    user_id: uuid.UUID | None = None,
    for_a_visitor: bool = False,
    commenters: tuple[uuid.UUID, ...] = (),
) -> EvidenceRun:
    run = SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        status="completed",
        error=error,
        user_id=user_id,
        initiated_by_publisher_fallback=for_a_visitor,
        channel_identity_id=None,
    )
    return EvidenceRun(run=run, rating=rating, comments=["Wrong"], commenters=list(commenters))  # type: ignore[arg-type]


def _message(role: str, content: str, calls=()) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content, tool_calls=list(calls))


class TestService:
    async def test_the_runs_of_somebody_being_erased_are_forgotten_before_a_write(
        self, monkeypatch, mock_db_session
    ):
        """Whose words a run holds is read with it, and checked again just before writing."""
        asker, commenter, publisher, gone = (uuid.uuid4() for _ in range(4))
        rows = [
            _row(user_id=asker, commenters=(commenter,)),
            _row(user_id=publisher, for_a_visitor=True),
            _row(user_id=gone),
            _row(user_id=asker, commenters=(gone,)),
        ]
        monkeypatch.setattr(authoring_repo, "evidence_runs", AsyncMock(return_value=rows))
        monkeypatch.setattr(conversation_repo, "get_messages_by_run", AsyncMock(return_value=[]))
        present = AsyncMock(return_value={asker, commenter})
        monkeypatch.setattr(personal_data_repo, "present_among", present)
        service = EvidenceService(mock_db_session)
        ctx = SimpleNamespace(organization_id=uuid.uuid4())
        pack = await service.for_agent(ctx, uuid.uuid4(), window_days=30)

        kept = await service.forget_erased(pack)

        assert [run.run_id for run in kept.runs] == [rows[0].run.id, rows[1].run.id]
        assert set(present.await_args.args[1]) == {asker, commenter, gone}

    async def test_an_agents_runs_are_read_with_their_turns(self, monkeypatch, mock_db_session):
        row = _row(error="x" * 3000)
        reads = AsyncMock(return_value=[row])
        monkeypatch.setattr(authoring_repo, "evidence_runs", reads)
        call = SimpleNamespace(tool_name="search_knowledge", args={"query": "q" * 400})
        monkeypatch.setattr(
            conversation_repo,
            "get_messages_by_run",
            AsyncMock(
                return_value=[
                    _message("user", "How long?"),
                    _message("assistant", "Let me look", [call]),
                    _message("assistant", "30 days."),
                ]
            ),
        )
        ctx = SimpleNamespace(organization_id=uuid.uuid4())

        pack = await EvidenceService(mock_db_session).for_agent(ctx, uuid.uuid4(), window_days=30)

        (packed,) = pack.runs
        assert packed.prompt == "How long?" and packed.answer == "30 days."
        assert packed.calls[0].startswith("search_knowledge(") and packed.calls[0].endswith(
            "[...])"
        )
        assert packed.error is not None and packed.error.endswith("[...]")
        assert reads.await_args.kwargs["organization_id"] == ctx.organization_id

    async def test_a_skills_evidence_is_the_rated_runs_that_opened_it(
        self, monkeypatch, mock_db_session
    ):
        reads = AsyncMock(return_value=[_row(rating=1)])
        monkeypatch.setattr(authoring_repo, "evidence_runs", reads)
        monkeypatch.setattr(conversation_repo, "get_messages_by_run", AsyncMock(return_value=[]))
        ctx = SimpleNamespace(organization_id=uuid.uuid4())

        pack = await EvidenceService(mock_db_session).for_skill(ctx, "refunds", window_days=7)

        assert reads.await_args.kwargs["skill_name"] == "refunds"
        assert pack.runs[0].prompt == "" and pack.runs[0].rating == 1


def _train_row(*, case_id: uuid.UUID, arm: SimpleNamespace, answer: str) -> SimpleNamespace:
    return SimpleNamespace(
        run=SimpleNamespace(id=uuid.uuid4(), user_id=None, initiated_by_publisher_fallback=False),
        case=SimpleNamespace(
            case_id=case_id,
            tags=None,
            input="How long do I have to return shoes?",
            created_by_user_id=None,
            asked_by_user_id=None,
            noted_by_user_id=None,
            history_author_ids=None,
        ),
        score=None,
        attempt=SimpleNamespace(answer=answer, error=None),
        arm=arm,
    )


class TestTrainingFeedback:
    @pytest.fixture
    def evaluated(self, monkeypatch) -> uuid.UUID:
        dataset_id = uuid.uuid4()
        monkeypatch.setattr(
            authoring_repo,
            "evaluated_datasets",
            AsyncMock(return_value=[SimpleNamespace(id=dataset_id)]),
        )
        return dataset_id

    async def test_only_the_newest_answer_per_case_is_read_and_an_ungraded_one_has_no_grade_line(
        self, monkeypatch, mock_db_session, evaluated
    ):
        case_id = uuid.uuid4()
        arm = SimpleNamespace(id=uuid.uuid4(), eval_run_id=uuid.uuid4())
        newest = _train_row(case_id=case_id, arm=arm, answer="90 days")
        older = _train_row(case_id=case_id, arm=arm, answer="60 days")
        monkeypatch.setattr(
            authoring_evidence, "accessible_ids", AsyncMock(return_value={evaluated})
        )
        monkeypatch.setattr(
            authoring_repo, "train_answers", AsyncMock(return_value=[newest, older])
        )
        monkeypatch.setattr(eval_run_repo, "list_cases", AsyncMock(return_value=[]))
        monkeypatch.setattr(eval_run_repo, "list_arms", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            EvalRunService, "outcomes", AsyncMock(return_value={case_id: (False, (), ())})
        )
        monkeypatch.setattr(
            EvalRunService,
            "compare",
            AsyncMock(return_value=SimpleNamespace(cases=[], verdict="better")),
        )
        ctx = SimpleNamespace(organization_id=uuid.uuid4())

        packed, feedback = await EvidenceService(mock_db_session)._train(
            ctx, uuid.uuid4(), window_days=30
        )

        (run,) = packed
        assert run.run_id == newest.run.id and run.answer == "90 days"
        assert run.status == "train_eval_failure" and run.comments == []
        assert "(untagged): 0/1 passed" in feedback

    async def test_a_failed_answer_s_grades_are_kept_apart_from_what_people_said(
        self, monkeypatch, mock_db_session, evaluated
    ):
        case_id = uuid.uuid4()
        arm = SimpleNamespace(id=uuid.uuid4(), eval_run_id=uuid.uuid4())
        row = _train_row(case_id=case_id, arm=arm, answer="90 days")
        row.score = SimpleNamespace(
            results=[
                {
                    "scorer": "judge",
                    "name": "Follows the policy",
                    "required": True,
                    "status": "fail",
                    "score": 0.0,
                    "reason": "1/5: It quotes 90 days",
                },
                {
                    "scorer": "check",
                    "name": "regex '30'",
                    "required": True,
                    "status": "fail",
                    "reason": "Does not match",
                },
            ],
            human_passed=None,
            human_note=None,
            reviewed_by_user_id=None,
        )
        monkeypatch.setattr(
            authoring_evidence, "accessible_ids", AsyncMock(return_value={evaluated})
        )
        monkeypatch.setattr(authoring_repo, "train_answers", AsyncMock(return_value=[row]))
        monkeypatch.setattr(eval_run_repo, "list_cases", AsyncMock(return_value=[]))
        monkeypatch.setattr(eval_run_repo, "list_arms", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            EvalRunService, "outcomes", AsyncMock(return_value={case_id: (False, (), ())})
        )
        monkeypatch.setattr(
            EvalRunService,
            "compare",
            AsyncMock(return_value=SimpleNamespace(cases=[], verdict="better")),
        )
        ctx = SimpleNamespace(organization_id=uuid.uuid4())

        (run,), _ = await EvidenceService(mock_db_session)._train(ctx, uuid.uuid4(), window_days=30)

        assert run.comments == []
        assert [(grade.name, grade.status) for grade in run.grades] == [
            ("Follows the policy", "fail"),
            ("regex '30'", "fail"),
        ]
        assert "Graded: judge/Follows the policy: 1/5: It quotes 90 days" in run.render()
        assert "It quotes 90 days" in run.quotable

    async def test_training_answers_of_datasets_the_caller_cannot_read_are_never_queried(
        self, monkeypatch, mock_db_session, evaluated
    ):
        monkeypatch.setattr(authoring_evidence, "accessible_ids", AsyncMock(return_value=set()))
        ctx = SimpleNamespace(organization_id=uuid.uuid4())

        packed, feedback = await EvidenceService(mock_db_session)._train(
            ctx, uuid.uuid4(), window_days=30
        )

        assert packed == [] and feedback == ""
        mock_db_session.execute.assert_not_awaited()


@pytest.mark.security
class TestImprovementEvidenceRefusals:
    async def test_reading_a_sessions_evidence_without_runs_view_is_refused(self, mock_db_session):
        ctx = SimpleNamespace(organization_id=uuid.uuid4(), has=lambda _perm: False)

        with pytest.raises(AuthorizationError, match="runs:view"):
            await EvidenceService(mock_db_session).for_improvement(ctx, uuid.uuid4())

    async def test_a_session_of_another_organization_reads_as_not_found(
        self, monkeypatch, mock_db_session
    ):
        lookup = AsyncMock(return_value=None)
        monkeypatch.setattr(improvement_repo, "get_run", lookup)
        ctx = SimpleNamespace(organization_id=uuid.uuid4(), has=lambda _perm: True)

        with pytest.raises(NotFoundError, match="Improvement session not found"):
            await EvidenceService(mock_db_session).for_improvement(ctx, uuid.uuid4())
        assert lookup.await_args.kwargs["organization_id"] == ctx.organization_id


class TestProposalSourceIdentities:
    async def _ids(self, monkeypatch, mock_db_session, *, request_id, request):
        monkeypatch.setattr(authoring_repo, "get_request", AsyncMock(return_value=request))
        ctx = SimpleNamespace(organization_id=uuid.uuid4())
        batch = SimpleNamespace(request_id=request_id)
        return await AuthoringService(mock_db_session).evidence_run_ids(ctx, batch)

    async def test_a_proposal_without_a_readable_request_has_no_source_runs(
        self, monkeypatch, mock_db_session
    ):
        assert await self._ids(monkeypatch, mock_db_session, request_id=None, request=None) == []
        assert (
            await self._ids(monkeypatch, mock_db_session, request_id=uuid.uuid4(), request=None)
            == []
        )

    async def test_the_requests_recorded_source_runs_are_read_back(
        self, monkeypatch, mock_db_session
    ):
        source = uuid.uuid4()
        request = SimpleNamespace(evidence={"source_run_ids": [str(source)]})

        ids = await self._ids(
            monkeypatch, mock_db_session, request_id=uuid.uuid4(), request=request
        )

        assert ids == [source]

    async def test_source_identities_that_no_longer_parse_are_refused(
        self, monkeypatch, mock_db_session
    ):
        request = SimpleNamespace(evidence={"source_run_ids": ["not-a-run"]})

        with pytest.raises(BadRequestError) as refused:
            await self._ids(monkeypatch, mock_db_session, request_id=uuid.uuid4(), request=request)
        assert refused.value.details == {"reason": "invalid_evidence"}
