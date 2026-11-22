"""The runtime/eval pipeline gates source identity, attribution and independent verification."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_ai import ModelRetry

from app.schemas.personal_context import (
    ContextDigest,
    ContextPacket,
    PersonalAdvice,
    PersonalReading,
    SourceEvidence,
    VerifiedReading,
    WorkTopic,
)
from app.services.proactive._context_pipeline import (
    CHUNK_CHARS,
    chunks,
    evidence_sources,
    extract_context,
    fingerprint,
    propose_context,
    select_topics,
    supported,
    with_human_answers,
)

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 22, tzinfo=UTC)


def packet(**changes: object) -> ContextPacket:
    return ContextPacket.model_validate(
        {
            "as_of": NOW,
            "subject_id": "a",
            "audience": "private",
            "profile": {},
            "memory": [],
            "tool_receipts": [],
            "current_state": {},
            "available_features": [],
            "changed_source_ids": [],
            "messages": [
                {
                    "id": "m",
                    "thread_id": "t",
                    "occurred_at": NOW,
                    "speaker_id": "a",
                    "role": "user",
                    "text": "Please prepare a team agenda every Thursday.",
                }
            ],
            **changes,
        }
    )


def evidence() -> SourceEvidence:
    return SourceEvidence(source_id="message:m", quote="team agenda every Thursday")


def topic(**changes: object) -> WorkTopic:
    return WorkTopic.model_validate(
        {
            "identity": "team-agenda",
            "summary": "Weekly agenda",
            "state": "open",
            "subject_owned": True,
            "evidence": [evidence().model_dump()],
            **changes,
        }
    )


def card(**changes: object) -> PersonalAdvice:
    return PersonalAdvice.model_validate(
        {
            "identity": "team-agenda",
            "kind": "routine",
            "title": "Weekly agenda",
            "detail": "You asked to prepare it every Thursday.",
            "chat_prompt": "Prepare the Thursday routine for my approval; ask only for the hour.",
            "evidence": [evidence().model_dump()],
            **changes,
        }
    )


class Reader:
    def __init__(self, **outputs: BaseModel | None) -> None:
        self.outputs = outputs
        self.calls: list[str] = []

    async def read[Result: BaseModel](
        self, *, stage: str, instructions: str, material: object, output_type: type[Result]
    ) -> Result | None:
        assert instructions and material
        self.calls.append(stage)
        value = self.outputs[stage]
        return None if value is None else output_type.model_validate(value.model_dump())


def test_chunking_preserves_the_entire_long_request_and_order() -> None:
    first = packet().messages[0].model_copy(update={"text": "x" * (CHUNK_CHARS + 3)})
    second = first.model_copy(update={"id": "last", "text": "My actual request"})
    result = chunks([first, second])
    assert "".join(turn.text for batch in result for turn in batch) == first.text + second.text
    assert all(sum(len(turn.text) for turn in batch) <= CHUNK_CHARS for batch in result)
    assert chunks([]) == []
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


def test_sources_are_explicit_and_blank_quotes_are_rejected() -> None:
    value = packet(
        memory=[{"id": "note", "statement": "English"}, {}],
        tool_receipts=[{"id": "answer", "status": "completed"}, {}],
        current_state={"tasks": [{"id": "task", "title": "Review"}, {}], "projects": False},
        available_features=[{"id": "tables", "available": True}, {}],
    )
    sources = evidence_sources(value)
    assert set(sources) == {
        "message:m",
        "memory:note",
        "receipt:answer",
        "task:task",
        "feature:tables",
    }
    assert supported(evidence(), sources)
    assert not supported(evidence().model_copy(update={"source_id": "missing"}), sources)
    assert not supported(evidence().model_copy(update={"quote": "not in source"}), sources)
    with pytest.raises(ValidationError):
        SourceEvidence(source_id="message:m", quote="    ")


def test_retrieval_drops_completed_and_noise_and_combines_real_evidence() -> None:
    rows = [
        ContextDigest(topics=[topic(), topic(identity="noise", state="not_work")]),
        ContextDigest(
            topics=[topic(identity="done"), topic(identity="done", state="completed"), topic()]
        ),
    ]
    result = select_topics(rows, packet())
    assert len(result) == 1 and result[0].identity == "team-agenda"
    assert result[0].evidence == [evidence()]


async def test_extraction_rejects_fabricated_citations_and_preserves_failure() -> None:
    assert await extract_context(Reader(extract=None), packet()) is None
    expected = ContextDigest(topics=[topic()])
    assert await extract_context(Reader(extract=expected), packet()) == expected
    with pytest.raises(ModelRetry):
        await extract_context(
            Reader(
                extract=ContextDigest(
                    topics=[topic(evidence=[{"source_id": "bad", "quote": "not real"}])]
                )
            ),
            packet(),
        )


async def test_a_verified_proposal_keeps_the_known_weekday_without_making_up_cron() -> None:
    expected = card()
    reader = Reader(
        propose=PersonalReading(opportunities=[expected]),
        verify=VerifiedReading(approved_identities=[expected.identity]),
    )
    result = await propose_context(reader, packet(), [ContextDigest(topics=[topic()])])
    assert result is not None
    assert result.opportunities == [expected]
    assert result is not None
    assert result.opportunities[0].proposed_schedule is None
    assert reader.calls == ["propose", "verify"]


async def test_a_shared_audience_never_receives_personal_proposals() -> None:
    reader = Reader()
    assert await propose_context(reader, packet(audience="shared"), []) == PersonalReading()
    assert reader.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"evidence": [{"source_id": "message:fake", "quote": "some quote"}]},
        {"kind": "feature_tip", "feature_id": "unavailable"},
    ],
)
async def test_invalid_sources_or_unavailable_features_never_reach_delivery(
    change: dict[str, object],
) -> None:
    reader = Reader(propose=PersonalReading(opportunities=[card(**change)]))
    result = await propose_context(reader, packet(), [])
    assert result is not None
    assert result.opportunities == [] and reader.calls == ["propose"]


async def test_assistant_claims_cannot_establish_a_personal_automation_request() -> None:
    source = (
        packet().messages[0].model_copy(update={"role": "assistant", "speaker_id": "assistant"})
    )
    reader = Reader(propose=PersonalReading(opportunities=[card()]))
    result = await propose_context(reader, packet(messages=[source.model_dump()]), [])
    assert result is not None
    assert result.opportunities == []


async def test_generation_or_verification_failure_is_not_successful_silence() -> None:
    assert await propose_context(Reader(propose=None), packet(), []) is None
    assert (
        await propose_context(
            Reader(propose=PersonalReading(opportunities=[card()]), verify=None), packet(), []
        )
        is None
    )
    with pytest.raises(ModelRetry):
        await propose_context(
            Reader(
                propose=PersonalReading(opportunities=[card()]),
                verify=VerifiedReading(approved_identities=["fabricated"]),
            ),
            packet(),
            [],
        )
    result = await propose_context(
        Reader(propose=PersonalReading(opportunities=[card()]), verify=VerifiedReading()),
        packet(),
        [],
    )
    assert result is not None
    assert result.opportunities == []


def receipt(**changes: object) -> dict[str, object]:
    return {
        "id": "answer",
        "action": "ask_user_question",
        "status": "completed",
        "answered_by_user_id": "a",
        "submitted_answers": {"When": ["thu 18"]},
        "submitted_at": NOW.isoformat(),
        **changes,
    }


def test_authenticated_question_answers_are_attributed_once() -> None:
    value = packet(tool_receipts=[receipt()])
    normalized = with_human_answers(value)
    assert normalized.messages[-1].text == "When: thu 18"
    assert normalized.messages[-1].speaker_id == "a"
    assert with_human_answers(normalized) == normalized
    encoded = packet(tool_receipts=[receipt(submitted_answers='{"When":["thu 18"]}')])
    assert with_human_answers(encoded).messages[-1].text == "When: thu 18"


@pytest.mark.parametrize(
    "changes",
    [
        {"id": None},
        {"action": "read_page"},
        {"status": "failed"},
        {"answered_by_user_id": "b"},
        {"submitted_answers": "not json"},
        {"submitted_answers": {"When": []}},
        {"submitted_at": None},
        {"submitted_at": "not a date"},
        {"submitted_at": "2026-11-21T12:00:00"},
    ],
)
def test_unattributed_remote_failed_or_undated_answers_do_not_become_human_input(
    changes: dict[str, object],
) -> None:
    value = packet(tool_receipts=[receipt(**changes)])
    assert with_human_answers(value).messages == value.messages


@pytest.mark.security
def test_erasure_and_revoked_sources_cannot_return_from_cached_evidence() -> None:
    value = packet(
        current_state={
            "source_access": {"t": "revoked"},
            "erased_source_ids": ["m"],
            "memory_erased_at": NOW.isoformat(),
        },
        tool_receipts=[receipt()],
    )
    assert with_human_answers(value).messages == []


async def test_short_source_aliases_resolve_to_actual_ids_and_preserve_literal_quote() -> None:
    digest = ContextDigest(
        topics=[
            topic(
                evidence=[
                    {
                        "source_id": "message:s0",
                        "quote": "PLEASE prepare a team agenda every Thursday.",
                    }
                ]
            )
        ]
    )
    result = await extract_context(Reader(extract=digest), packet())
    assert result is not None
    ref = result.topics[0].evidence[0]
    assert ref.source_id == "message:m"
    assert ref.quote == packet().messages[0].text
    assert supported(ref, evidence_sources(packet()))


@pytest.mark.security
@pytest.mark.parametrize("change", ["foreign_task", "unknown_resource", "completed_task"])
async def test_proposals_cannot_borrow_other_tasks_or_invent_a_resource(change: str) -> None:
    value = packet(
        current_state={
            "tasks": [
                {
                    "id": "t",
                    "owner": "other" if change == "foreign_task" else "a",
                    "status": "done" if change == "completed_task" else "planned",
                    "title": "Review this release",
                }
            ]
        }
    )
    proposed = card(
        kind="task",
        resource_ids=["missing" if change == "unknown_resource" else "t"],
        evidence=[SourceEvidence(source_id="task:t", quote="Review this release")],
    )
    result = await propose_context(
        Reader(propose=PersonalReading(opportunities=[proposed])), value, []
    )
    assert result is not None and result.opportunities == []


async def test_verifier_can_repair_wording_but_cannot_change_kind_or_borrow_evidence() -> None:
    original = card()
    fixed = card(chat_prompt="Prepare the Thursday agenda at the known time for approval.")
    result = await propose_context(
        Reader(
            propose=PersonalReading(opportunities=[original]),
            verify=VerifiedReading(corrections=[fixed]),
        ),
        packet(),
        [],
    )
    assert result is not None and result.opportunities == [fixed]
    result = await propose_context(
        Reader(
            propose=PersonalReading(opportunities=[original]),
            verify=VerifiedReading(corrections=[card(kind="attention")]),
        ),
        packet(),
        [],
    )
    assert result is not None and result.opportunities == []


def test_one_underlying_job_is_not_returned_twice() -> None:
    with pytest.raises(ValidationError, match="underlying job"):
        PersonalReading(opportunities=[card(), card()])


async def test_changed_quote_wording_is_not_repaired_as_a_real_source() -> None:
    with pytest.raises(ModelRetry):
        await extract_context(
            Reader(
                extract=ContextDigest(
                    topics=[
                        topic(
                            evidence=[
                                {"source_id": "message:s0", "quote": "team agenda every Friday"}
                            ]
                        )
                    ]
                )
            ),
            packet(),
        )


def test_resource_excerpts_have_an_explicit_truncation_marker() -> None:
    from app.services.proactive._context_snapshot import json_record

    value = json_record({"id": "x", "content": "x" * 3000, "nested": [{"title": "Kept"}]})
    assert value == {
        "id": "x",
        "content": "x" * 2000,
        "nested": [{"title": "Kept"}],
        "text_truncated": True,
    }


async def test_conversation_inventory_pages_every_visible_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.core.permissions import AuthContext, OrgRoleName
    from app.db.models.conversation import Conversation
    from app.services.conversation import ConversationService
    from app.services.proactive._personal import PersonalLook

    ctx = AuthContext(organization_id=uuid4(), user_id=uuid4(), role=OrgRoleName.OWNER)
    rows = [
        Conversation(id=uuid4(), organization_id=ctx.organization_id, user_id=ctx.user_id)
        for _ in range(101)
    ]
    monkeypatch.setattr(
        ConversationService,
        "list_conversations",
        AsyncMock(side_effect=[(rows[:100], 101), (rows[100:], 101)]),
    )
    assert await PersonalLook(AsyncMock())._conversations(ctx) == rows
