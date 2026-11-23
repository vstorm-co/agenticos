"""The runtime/eval pipeline gates source identity, attribution and independent verification."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_ai import ModelRetry

from app.schemas.personal_context import (
    ContextDigest,
    ContextPacket,
    ConversationContext,
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
    source_excerpt,
    source_metadata,
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
        value = (
            self.outputs.get(stage, self.outputs.get("verify"))
            if stage == "verify_starters"
            else self.outputs[stage]
        )
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
    extracted = await extract_context(Reader(extract=expected), packet())
    assert extracted is not None and extracted.topics[0].identity == expected.topics[0].identity
    assert extracted.topics[0].evidence[0].quote == packet().messages[0].text
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
    reader = Reader(
        propose=PersonalReading(opportunities=[card()]),
        verify=VerifiedReading(approved_identities=[card().identity]),
    )
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
        Reader(
            propose=PersonalReading(opportunities=[proposed]),
            verify=VerifiedReading(approved_identities=[proposed.identity]),
        ),
        value,
        [],
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


async def test_verification_can_recover_intent_lost_by_a_narrow_quote() -> None:
    user = (
        packet()
        .messages[0]
        .model_copy(
            update={
                "text": "Build me an agent that does this: prepare a team agenda every Thursday."
            }
        )
    )
    assistant = user.model_copy(
        update={
            "id": "response",
            "role": "assistant",
            "speaker_id": "assistant",
            "text": "I created an agent for the agenda.",
        }
    )
    value = packet(messages=[user.model_dump(), assistant.model_dump()])
    proposed = card(
        evidence=[SourceEvidence(source_id="message:response", quote="I created an agent")]
    )
    fixed = card(
        evidence=[SourceEvidence(source_id="message:m", quote="Build me an agent that does this")]
    )
    result = await propose_context(
        Reader(
            propose=PersonalReading(
                opportunities=[proposed],
                starters=["Fix my existing agent", "Prepare my weekly agenda"],
            ),
            verify=VerifiedReading(corrections=[fixed], approved_starter_indices=[1]),
        ),
        value,
        [
            ContextDigest(
                topics=[
                    topic(
                        evidence=[
                            SourceEvidence(
                                source_id="message:m", quote="prepare a team agenda every Thursday"
                            )
                        ]
                    )
                ]
            )
        ],
    )
    assert result is not None and result.opportunities == [fixed]
    assert result.starters == ["Prepare my weekly agenda"]


async def test_starters_are_checked_even_without_a_candidate_card() -> None:
    result = await propose_context(
        Reader(propose=PersonalReading(starters=["An unsupported task"]), verify=VerifiedReading()),
        packet(),
        [],
    )
    assert result == PersonalReading()


@pytest.mark.security
async def test_attention_needs_current_resource_evidence_not_a_historical_assistant_claim() -> None:
    source = (
        packet().messages[0].model_copy(update={"role": "assistant", "speaker_id": "assistant"})
    )
    proposed = card(kind="attention")
    reader = Reader(
        propose=PersonalReading(opportunities=[proposed]),
        verify=VerifiedReading(approved_identities=[proposed.identity]),
    )
    result = await propose_context(
        reader,
        packet(
            messages=[source.model_dump()],
            current_state={"routines": [], "routines_complete": True},
        ),
        [],
    )
    assert result == PersonalReading()


async def test_attention_can_cite_a_current_project_record() -> None:
    proposed = card(
        kind="attention",
        evidence=[SourceEvidence(source_id="project:p", quote="Review the release")],
        resource_ids=["p"],
    )
    value = packet(current_state={"projects": [{"id": "p", "description": "Review the release"}]})
    result = await propose_context(
        Reader(
            propose=PersonalReading(opportunities=[proposed]),
            verify=VerifiedReading(approved_identities=[proposed.identity]),
        ),
        value,
        [],
    )
    assert result is not None and result.opportunities == [proposed]


async def test_an_existing_empty_board_is_a_valid_target_for_tracking_work() -> None:
    value = packet(current_state={"task_boards": [{"id": "b", "owner": "a", "tasks": []}]})
    proposed = card(kind="task", resource_ids=["b"])
    result = await propose_context(
        Reader(
            propose=PersonalReading(opportunities=[proposed]),
            verify=VerifiedReading(approved_identities=[proposed.identity]),
        ),
        value,
        [],
    )
    assert result is not None and result.opportunities == [proposed]
    assert "board:b" in evidence_sources(value)


async def test_local_weekday_metadata_uses_the_profile_timezone() -> None:
    class CapturingReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            assert isinstance(material, dict)
            if stage == "propose":
                facts = material["source_metadata"]["message:m"]
                assert facts["local_date"] == "2026-11-20"
                assert facts["local_isoweekday"] == 5
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    turn = (
        packet()
        .messages[0]
        .model_copy(update={"occurred_at": datetime(2026, 11, 19, 23, 30, tzinfo=UTC)})
    )
    value = packet(profile={"time_zone": "Europe/Warsaw"}, messages=[turn.model_dump()])
    await propose_context(
        CapturingReader(propose=PersonalReading()), value, [ContextDigest(topics=[topic()])]
    )


async def test_existing_table_metadata_can_support_a_recurring_work_proposal() -> None:
    value = packet(current_state={"tables": [{"id": "finance", "name": "Finance Tasks"}]})
    proposed = card(resource_ids=["finance"])
    result = await propose_context(
        Reader(
            propose=PersonalReading(opportunities=[proposed]),
            verify=VerifiedReading(approved_identities=[proposed.identity]),
        ),
        value,
        [],
    )
    assert result is not None and result.opportunities == [proposed]
    assert "table:finance" in evidence_sources(value)


@pytest.mark.parametrize(
    "case", ["assistant", "attributed", "web", "retained", "project", "anonymous"]
)
def test_source_speaker_uses_server_attribution_instead_of_a_shared_owner(case: str) -> None:
    from uuid import uuid4

    from app.db.models.agent_run import AgentRun
    from app.db.models.conversation import Conversation, Message
    from app.services.proactive._personal import source_speaker

    owner, caller = uuid4(), uuid4()
    conversation = Conversation(user_id=owner, project_id=uuid4() if case == "project" else None)
    message = Message(
        role="assistant" if case == "assistant" else "user",
        author_user_id=caller if case == "attributed" else None,
    )
    run = (
        AgentRun(surface="web", user_id=caller if case != "anonymous" else None)
        if case in {"web", "anonymous"}
        else None
    )
    expected = {
        "assistant": "assistant",
        "attributed": str(caller),
        "web": str(caller),
        "retained": str(owner),
        "project": "unknown",
        "anonymous": "unknown",
    }[case]
    assert source_speaker(message, run, conversation) == expected


async def test_a_starter_verification_failure_preserves_failure_instead_of_silence() -> None:
    assert (
        await propose_context(
            Reader(propose=PersonalReading(starters=["Review my tasks"]), verify_starters=None),
            packet(),
            [],
        )
        is None
    )


async def test_card_verification_does_not_borrow_another_threads_historical_state() -> None:
    class ScopedReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            if stage == "verify":
                assert isinstance(material, dict)
                assert "message:other" not in material["original_sources"]
                assert "message:m" in material["original_sources"]
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    other = (
        packet()
        .messages[0]
        .model_copy(
            update={
                "id": "other",
                "thread_id": "unrelated",
                "role": "assistant",
                "speaker_id": "assistant",
                "text": "An unrelated routine was paused last year.",
            }
        )
    )
    value = packet(messages=[packet().messages[0].model_dump(), other.model_dump()])
    reader = ScopedReader(
        propose=PersonalReading(opportunities=[card()]),
        verify=VerifiedReading(approved_identities=[card().identity]),
    )
    result = await propose_context(
        reader,
        value,
        [
            ContextDigest(
                topics=[
                    topic(),
                    topic(
                        identity="other-job",
                        evidence=[
                            SourceEvidence(
                                source_id="message:other", quote="An unrelated routine was paused"
                            )
                        ],
                    ),
                ]
            )
        ],
    )
    assert result is not None and result.opportunities == [card()]


@pytest.mark.security
async def test_extraction_cannot_cite_context_that_was_not_supplied_to_its_stage() -> None:
    value = packet(memory=[{"id": "hidden", "statement": "A memory not shown to extraction"}])
    with pytest.raises(ModelRetry):
        await extract_context(
            Reader(
                extract=ContextDigest(
                    topics=[
                        topic(
                            evidence=[
                                SourceEvidence(
                                    source_id="memory:hidden", quote="A memory not shown"
                                )
                            ]
                        )
                    ]
                )
            ),
            value,
        )


@pytest.mark.security
async def test_cached_source_fragments_cannot_fabricate_a_contiguous_quote() -> None:
    turn = (
        packet()
        .messages[0]
        .model_copy(
            update={
                "text": "first part\nsecond part",
                "source_fragments": ["first part", "second part"],
            }
        )
    )
    sources = evidence_sources(packet(messages=[turn.model_dump()]))
    invented = SourceEvidence(source_id="message:m", quote="part second")
    assert not supported(invented, sources)
    with pytest.raises(ValueError, match="original fragment"):
        source_excerpt(invented, sources)
    literal = SourceEvidence(source_id="message:m", quote="second part")
    assert supported(literal, sources)
    assert source_excerpt(literal, sources) == "second part"
    contiguous = evidence_sources(
        packet(messages=[turn.model_copy(update={"source_fragments": None}).model_dump()])
    )
    assert supported(invented, contiguous)


async def test_verifier_retains_distinct_fragments_of_the_same_source() -> None:
    class FragmentReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            if stage == "verify":
                assert isinstance(material, dict)
                assert set(material["original_sources"]["message:m"]) == {
                    "Please prepare a team agenda every Thursday.",
                    "Deliver it to my private Inbox.",
                }
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    fragments = ["Please prepare a team agenda every Thursday.", "Deliver it to my private Inbox."]
    turn = (
        packet()
        .messages[0]
        .model_copy(update={"text": "\n".join(fragments), "source_fragments": fragments})
    )
    advice = card(
        evidence=[
            evidence().model_dump(),
            {"source_id": "message:m", "quote": "Deliver it to my private Inbox."},
        ]
    )
    result = await propose_context(
        FragmentReader(
            propose=PersonalReading(opportunities=[advice]),
            verify=VerifiedReading(approved_identities=[advice.identity]),
        ),
        packet(messages=[turn.model_dump()]),
        [ContextDigest(topics=[topic()])],
    )
    assert result is not None and result.opportunities == [advice]


@pytest.mark.parametrize("thread", ["t", "unrelated", None])
async def test_card_verifier_receives_only_related_question_receipts(thread: str | None) -> None:
    class ReceiptReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            if stage == "verify":
                assert isinstance(material, dict)
                assert ("receipt:answer" in material["original_sources"]) is (thread == "t")
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    value = packet(tool_receipts=[receipt(thread_id=thread), {"id": None}])
    result = await propose_context(
        ReceiptReader(
            propose=PersonalReading(opportunities=[card()]),
            verify=VerifiedReading(approved_identities=[card().identity]),
        ),
        value,
        [ContextDigest(topics=[topic()])],
    )
    assert result is not None and result.opportunities == [card()]


async def test_card_verifier_keeps_an_answer_cited_without_thread_metadata() -> None:
    advice = card(
        evidence=[
            SourceEvidence(source_id="message:answer:answer", quote="When: thu 18").model_dump()
        ]
    )

    class AnswerReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            if stage == "verify":
                assert isinstance(material, dict)
                assert "receipt:answer" in material["original_sources"]
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    result = await propose_context(
        AnswerReader(
            propose=PersonalReading(opportunities=[advice]),
            verify=VerifiedReading(approved_identities=[advice.identity]),
        ),
        packet(tool_receipts=[receipt()]),
        [],
    )
    assert result is not None and result.opportunities == [advice]


@pytest.mark.parametrize("latest_state", ["completed", "open"])
def test_latest_topic_state_uses_source_chronology_not_conversation_order(
    latest_state: str,
) -> None:
    from datetime import timedelta

    old = packet().messages[0]
    latest = old.model_copy(
        update={"id": "new", "thread_id": "another", "occurred_at": NOW + timedelta(hours=1)}
    )
    value = packet(messages=[latest.model_dump(), old.model_dump()])
    recent = topic(
        state=latest_state, evidence=[{"source_id": "message:new", "quote": evidence().quote}]
    )
    older = topic(state="open" if latest_state == "completed" else "completed")
    result = select_topics([ContextDigest(topics=[recent]), ContextDigest(topics=[older])], value)
    assert len(result) == (1 if latest_state == "open" else 0)


async def test_proposal_receipt_retrieval_does_not_send_unrelated_answer_history() -> None:
    class BoundedReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            if stage == "propose":
                assert isinstance(material, dict)
                assert "receipt:answer" not in material["sources"]
                assert "message:answer:answer" not in material["sources"]
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    assert (
        await propose_context(
            BoundedReader(propose=PersonalReading()),
            packet(tool_receipts=[receipt(thread_id="old")]),
            [ContextDigest(topics=[topic()])],
        )
        == PersonalReading()
    )


async def test_verifier_receives_human_words_instead_of_a_clock_allowlist() -> None:
    proposed = card(chat_prompt="Set it up Thursday at 18:00.")

    class TemporalReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            if stage == "verify":
                assert isinstance(material, dict)
                assert "unconfirmed_local_hours" not in material
                assert material["original_sources"]["message:m"] == (packet().messages[0].text,)
                assert "Event timestamps establish when" in instructions
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    result = await propose_context(
        TemporalReader(propose=PersonalReading(opportunities=[proposed]), verify=VerifiedReading()),
        packet(),
        [ContextDigest(topics=[topic()])],
    )
    assert result is not None and result.opportunities == []


async def test_a_short_native_answer_can_confirm_a_padded_clock_hour() -> None:
    answer = SourceEvidence(source_id="message:answer:answer", quote="When: thu 18")
    advice = card(
        chat_prompt="Prepare Thursday at 18:00.",
        proposed_schedule="Thursday 18:00",
        evidence=[evidence().model_dump(), answer.model_dump()],
    )
    value = packet(tool_receipts=[receipt(thread_id="t")])
    result = await propose_context(
        Reader(
            propose=PersonalReading(opportunities=[advice]),
            verify=VerifiedReading(approved_identities=[advice.identity]),
        ),
        value,
        [ContextDigest(topics=[topic(evidence=[evidence().model_dump(), answer.model_dump()])])],
    )
    assert result is not None and result.opportunities == [advice]


async def test_retrieval_includes_bounded_related_failed_operation_metadata() -> None:
    class FailureReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            if stage == "propose":
                assert isinstance(material, dict)
                receipts = {key for key in material["sources"] if key.startswith("receipt:")}
                assert len(receipts) == 8
                assert "receipt:unrelated" not in receipts
                assert "receipt:unknown-job" in receipts
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    receipts: list[dict[str, object]] = [
        {
            "id": f"failure-{i}",
            "thread_id": "t",
            "action": "create_routine",
            "status": "failed",
            "occurred_at": f"2026-11-{i + 1:02}T12:00:00Z",
        }
        for i in range(10)
    ]
    receipts.extend(
        [
            {"id": "unrelated", "thread_id": "other", "status": "failed"},
            {"id": "unknown-job", "status": "failed", "occurred_at": "2026-11-20T12:00:00Z"},
            {"id": None, "status": "failed"},
            {"id": "malformed", "status": "failed", "thread_id": []},
        ]
    )
    result = await propose_context(
        FailureReader(propose=PersonalReading()),
        packet(tool_receipts=receipts),
        [ContextDigest(topics=[topic()])],
    )
    assert result == PersonalReading()


@pytest.mark.parametrize("hour", ["18:00", "09:00"])
async def test_verifier_can_distinguish_submitted_values_from_unselected_options(
    hour: str,
) -> None:
    native = receipt(thread_id="t", questions={"When": ["Monday 09:00", "Friday 15:00"]})
    ref = SourceEvidence(source_id="receipt:answer", quote="thu 18")
    advice = card(
        chat_prompt=f"Prepare it at {hour}.",
        proposed_schedule=f"Thursday {hour}",
        evidence=[evidence().model_dump(), ref.model_dump()],
    )
    result = await propose_context(
        Reader(
            propose=PersonalReading(opportunities=[advice]),
            verify=VerifiedReading(
                approved_identities=[advice.identity] if hour == "18:00" else []
            ),
        ),
        packet(tool_receipts=[native]),
        [ContextDigest(topics=[topic(evidence=[evidence().model_dump(), ref.model_dump()])])],
    )
    assert result is not None and len(result.opportunities) == (1 if hour == "18:00" else 0)


@pytest.mark.parametrize("kind", ["attention", "task"])
async def test_a_current_task_deadline_is_not_an_unconfirmed_new_schedule(kind: str) -> None:
    value = packet(
        messages=[],
        current_state={
            "tasks": [
                {
                    "id": "task",
                    "title": "Review release",
                    "owner": "a",
                    "status": "planned",
                    "due_at": "2026-11-21T16:00:00Z",
                }
            ]
        },
    )
    advice = card(
        kind=kind,
        title="Review release",
        detail="The task was due at 16:00 UTC yesterday.",
        chat_prompt="Help me finish the existing task.",
        proposed_schedule=None,
        resource_ids=["task"],
        evidence=[{"source_id": "task:task", "quote": "Review release"}],
    )
    result = await propose_context(
        Reader(
            propose=PersonalReading(opportunities=[advice]),
            verify=VerifiedReading(approved_identities=[advice.identity]),
        ),
        value,
        [],
    )
    assert result is not None and result.opportunities == [advice]


async def test_linked_answers_reach_proposal_and_verifier_without_index_citations() -> None:
    class AnswerReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            if stage == "propose":
                assert isinstance(material, dict)
                assert material["sources"]["message:answer:answer"] == ("When: thu 18",)
                assert "receipt:answer" in material["sources"]
            if stage == "verify":
                assert isinstance(material, dict)
                assert material["original_sources"]["message:answer:answer"] == ("When: thu 18",)
                assert "unconfirmed_local_hours" not in material
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    advice = card(
        chat_prompt="Prepare the Thursday routine at 18:00.", proposed_schedule="Thursday 18:00"
    )
    result = await propose_context(
        AnswerReader(
            propose=PersonalReading(opportunities=[advice]),
            verify=VerifiedReading(approved_identities=[advice.identity]),
        ),
        packet(tool_receipts=[receipt(thread_id="t")]),
        [ContextDigest(topics=[topic()])],
    )
    assert result is not None and result.opportunities == [advice]


async def test_linked_answer_retrieval_is_bounded_and_marks_partial_context() -> None:
    class BoundedReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            assert stage == "propose" and isinstance(material, dict)
            answers = {
                key: value
                for key, value in material["sources"].items()
                if key.startswith("message:answer:")
            }
            assert len(answers) == 8
            assert all(
                len(fragment) <= 2000 for fragments in answers.values() for fragment in fragments
            )
            assert all(material["source_metadata"][key]["context_truncated"] for key in answers)
            assert "message:answer:old-0" not in answers
            assert "message:answer:unrelated" not in answers
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    receipts = [
        receipt(id=f"old-{i}", thread_id="t", submitted_answers={"Details": [str(i) + "x" * 3000]})
        for i in range(10)
    ]
    receipts.append(receipt(id="unrelated", thread_id="other"))
    assert (
        await propose_context(
            BoundedReader(propose=PersonalReading()),
            packet(tool_receipts=receipts),
            [ContextDigest(topics=[topic()])],
        )
        == PersonalReading()
    )


def test_proposal_can_restore_a_cached_answer_without_unbounding_extraction_segments() -> None:
    value = with_human_answers(packet(tool_receipts=[receipt(thread_id="t")]))
    answer = next(turn for turn in value.messages if turn.id == "answer:answer")
    clipped = answer.model_copy(update={"text": "When", "source_fragments": ["When"]})
    cached = value.model_copy(update={"messages": [clipped]})
    assert with_human_answers(cached).messages[0].text == "When"
    assert with_human_answers(cached, restore_cached=True).messages[0].text == "When: thu 18"


@pytest.mark.security
@pytest.mark.parametrize("fence", ["thread", "receipt", "erased"])
def test_native_answers_cannot_restore_revoked_or_erased_sources(fence: str) -> None:
    state = (
        {"source_access": {"t" if fence == "thread" else "receipt:answer": "revoked"}}
        if fence != "erased"
        else {"erased_source_ids": ["answer:answer"]}
    )
    value = packet(messages=[], tool_receipts=[receipt(thread_id="t")], current_state=state)
    assert with_human_answers(value, restore_cached=True).messages == []


def test_completed_index_segment_keys_cannot_disagree_with_its_digests() -> None:
    with pytest.raises(ValidationError, match="one digest"):
        ConversationContext(revision="r", digests=[], messages=[], receipts=[], part_keys=["extra"])


async def test_restored_answers_preserve_citations_from_runtime_value_only_turns() -> None:
    answer = receipt(
        thread_id="t",
        submitted_answers={
            "When": ["thu 18"],
            "Delivery": ["Post to team channel"],
            "Sources": ["web search"],
        },
    )
    quote = "thu 18 Post to team channel web search"
    native = (
        packet()
        .messages[0]
        .model_copy(update={"id": "answer:answer", "text": quote, "source_fragments": [quote]})
    )
    value = packet(messages=[native.model_dump()], tool_receipts=[answer])
    ref = SourceEvidence(source_id="message:answer:answer", quote=quote)
    indexed = topic(evidence=[ref.model_dump()], intent="explicit_automation")

    class RestoredReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            assert stage == "propose" and isinstance(material, dict)
            assert [row["identity"] for row in material["topics"]] == [indexed.identity]
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    restored = with_human_answers(value, restore_cached=True)
    assert supported(ref, evidence_sources(restored))
    assert not supported(
        SourceEvidence(source_id=ref.source_id, quote="Monday 09:00"),
        evidence_sources(restored),
    )
    assert (
        await propose_context(
            RestoredReader(propose=PersonalReading()), value, [ContextDigest(topics=[indexed])]
        )
        == PersonalReading()
    )


@pytest.mark.security
def test_unknown_cached_answer_text_cannot_be_restored_as_human_evidence() -> None:
    invented = (
        packet()
        .messages[0]
        .model_copy(
            update={"id": "answer:answer", "text": "Monday 09:00", "source_fragments": None}
        )
    )
    value = packet(messages=[invented.model_dump()], tool_receipts=[receipt(thread_id="t")])
    restored = with_human_answers(value, restore_cached=True)
    assert restored.messages[0].source_fragments is None
    assert not supported(
        SourceEvidence(source_id="message:answer:answer", quote="Monday 09:00"),
        evidence_sources(restored),
    )


@pytest.mark.parametrize(
    "wording",
    [
        "nächsten Donnerstag um sechs abends",
        "los jueves a las seis",
        "co czwartek o osiemnastej",
        "thu 18",
        "次の木曜日18時",
    ],
)
async def test_multilingual_native_answers_are_supplied_verbatim_not_parsed(wording: str) -> None:
    questions = [{"header": "Schedule", "question": "Which day and local time should it run?"}]
    native = receipt(thread_id="t", questions=questions, submitted_answers={"Schedule": [wording]})
    advice = card(chat_prompt="Prepare it on Thursday at 18:00 for approval.")

    class ContextReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            assert isinstance(material, dict)
            if stage in {"propose", "verify"}:
                assert material["tool_receipts"][0]["questions"] == questions
                assert material["tool_receipts"][0]["submitted_answers"] == {"Schedule": [wording]}
                facts = material["source_metadata"]["message:answer:answer"]
                assert facts["thread_id"] == "t"
                assert facts["receipt_source_id"] == "receipt:answer"
                assert facts["role"] == "user" and facts["speaker_id"] == "a"
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    result = await propose_context(
        ContextReader(
            propose=PersonalReading(opportunities=[advice]),
            verify=VerifiedReading(approved_identities=[advice.identity]),
        ),
        packet(tool_receipts=[native]),
        [ContextDigest(topics=[topic()])],
    )
    assert result is not None and result.opportunities == [advice]


@pytest.mark.parametrize(
    "instant,local,weekday",
    [
        ("2026-11-22T23:30:00+00:00", "2026-11-23T00:30:00+01:00", "Monday"),
        ("2026-10-25T00:30:00+00:00", "2026-10-25T02:30:00+02:00", "Sunday"),
        ("2026-10-25T01:30:00+00:00", "2026-10-25T02:30:00+01:00", "Sunday"),
    ],
)
def test_event_metadata_retains_timezone_offset_at_midnight_and_dst(
    instant: str, local: str, weekday: str
) -> None:
    value = packet(profile={"time_zone": "Europe/Warsaw"})
    value.messages[0].occurred_at = datetime.fromisoformat(instant)
    facts = source_metadata(value)["message:m"]
    assert facts["occurred_at"] == instant
    assert facts["local_datetime"] == local
    assert facts["local_weekday"] == weekday
    assert facts["time_zone"] == "Europe/Warsaw"


def test_undated_tools_and_unknown_timezone_do_not_gain_invented_dates() -> None:
    facts = source_metadata(packet(tool_receipts=[{}, receipt(submitted_at="invalid")]))
    assert facts["message:m"]["local_datetime"] is None
    assert facts["message:m"]["local_weekday"] is None
    assert facts["receipt:answer"]["timestamp_invalid"] is True


async def test_extraction_keeps_structured_questions_and_message_chronology() -> None:
    questions = [{"header": "When", "question": "x" * 2500 + "Choose a local preparation time?"}]

    class ExtractionReader(Reader):
        async def read[Result: BaseModel](
            self, *, stage: str, instructions: str, material: object, output_type: type[Result]
        ) -> Result | None:
            assert isinstance(material, dict)
            assert material["as_of"] == NOW.isoformat()
            assert material["time_zone"] == "Europe/Warsaw"
            assert material["messages"][0]["local_datetime"] == "2026-11-22T01:00:00+01:00"
            native = material["tool_receipts"][0]
            assert native["questions"] == questions
            assert native["answer_source_id"] == "message:answer:answer"
            assert native["answered_by_user_id"] == "a"
            assert native["occurred_at"] == NOW.isoformat()
            return await super().read(
                stage=stage, instructions=instructions, material=material, output_type=output_type
            )

    await extract_context(
        ExtractionReader(extract=ContextDigest()),
        packet(
            profile={"time_zone": "Europe/Warsaw"},
            tool_receipts=[receipt(thread_id="t", questions=questions)],
        ),
    )


@pytest.mark.parametrize(
    ("first", "last", "expected"),
    [
        ("2026-11-22T00:05:00+00:00", "2026-11-22T23:55:00+00:00", 1),
        ("2026-11-21T23:55:00+00:00", "2026-11-22T00:05:00+00:00", 0),
    ],
)
def test_topic_selection_groups_source_days_in_the_persons_timezone(
    first: str, last: str, expected: int
) -> None:
    value = packet(profile={"time_zone": "Europe/Warsaw"})
    value.messages = [
        value.messages[0].model_copy(
            update={"id": identifier, "occurred_at": datetime.fromisoformat(at)}
        )
        for identifier, at in [("first", first), ("last", last)]
    ]
    rows = [
        ContextDigest(
            topics=[
                topic(
                    state="completed",
                    intent="one_off",
                    evidence=[
                        {
                            "source_id": f"message:{identifier}",
                            "quote": "team agenda every Thursday",
                        }
                    ],
                )
            ]
        )
        for identifier in ["first", "last"]
    ]
    assert len(select_topics(rows, value)) == expected
