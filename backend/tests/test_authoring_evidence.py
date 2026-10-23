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

from app.repositories import authoring_repo, conversation_repo, personal_data_repo
from app.repositories.authoring import EvidenceRun
from app.schemas.authoring import MAX_EVIDENCE_ITEMS, MAX_QUOTE_CHARS, EvidenceQuote
from app.services import authoring_evidence
from app.services.authoring_evidence import EvidencePack, EvidenceService, PackedRun

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
            "rated_down": 1,
            "rated_up": 1,
            "commented": 1,
            "conversation_ids": [str(shared)],
        }

    def test_evidence_that_fits_is_read_at_once_and_otherwise_in_groups(self, monkeypatch):
        runs = [_packed() for _ in range(7)]

        assert EvidencePack().groups() == []
        assert EvidencePack(runs=runs).groups() == [runs]
        monkeypatch.setattr(authoring_evidence, "PACK_BUDGET_CHARS", 10)
        assert [len(group) for group in EvidencePack(runs=runs).groups()] == [5, 2]

    def test_rendering_several_runs_separates_them(self):
        assert authoring_evidence.render_runs([_packed(), _packed()]).count("## Run") == 2


class TestVerify:
    def test_a_quote_found_in_its_run_is_kept_whitespace_and_all(self):
        run = _packed()
        pack = EvidencePack(runs=[run])

        kept, dropped = pack.verify([EvidenceQuote(run_id=run.run_id, quote="90 days to return")])

        assert kept == [{"run_id": str(run.run_id), "quote": "90 days to return"}]
        assert dropped == 0

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
