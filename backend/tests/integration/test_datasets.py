"""Datasets against Postgres - versions that do not move, and access that holds.

The claims a mocked session cannot make:

- every change to a dataset's cases is a new version, and the version before it
  still reads the cases it held, byte for byte;
- a CSV of a hundred cases imports as one version and exports back unchanged;
- "Add to dataset" turns a rated-down answer into a case linked to its run, and
  refuses an answer from another organization exactly as one that does not exist;
- a member the dataset was not shared with can neither read it nor change it,
  whatever their role allows elsewhere, and a grant widens that for one dataset.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.exceptions import ValidationError as InvalidCaseError
from app.core.permissions import AuthContext, OrgRoleName, Scope
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.dataset import Dataset, DatasetCase, DatasetVersion, DatasetVersionCase
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.db.models.user import User
from app.repositories import dataset_repo, project_repo
from app.repositories._visibility import reached_by_scope, shared_with_caller, visible_to_caller
from app.schemas.dataset import (
    DatasetCaseCreate,
    DatasetCaseFromMessage,
    DatasetCaseUpdate,
    DatasetCreate,
    DatasetList,
    DatasetUpdate,
)
from app.services import dataset as dataset_service
from app.services.access import _scope_allows
from app.services.conversation import ConversationService
from app.services.dataset import DatasetService
from app.services.dataset_files import COLUMNS
from app.services.project import ProjectService
from app.services.user import UserService

pytestmark = pytest.mark.anyio

_START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org


async def _member(db, org: Organization, role: OrgRoleName) -> AuthContext:
    person = await _user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=person.id, role=role.value
        )
    )
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=org.id, role=role.value)


async def _owner(db) -> AuthContext:
    person = await _user(db)
    org = await _org(db, owner=person)
    return AuthContext(user_id=person.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


async def _rated_down_turn(
    db, ctx: AuthContext, *, comment: str | None = "Wrong refund window"
) -> tuple[AgentRun, Message]:
    """A conversation with an earlier turn, then a question and an answer rated down."""
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    conversation = Conversation(
        id=uuid.uuid4(), user_id=ctx.user_id, organization_id=ctx.organization_id, title="Refunds"
    )
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        conversation_id=conversation.id,
        status="completed",
        started_at=_START,
        ended_at=_START + timedelta(minutes=1),
    )
    db.add(run)
    await db.flush()
    turns = [
        ("user", "Hi, I bought a kettle", None),
        ("assistant", "Hello! How can I help?", None),
        ("system", "summary", None),
        ("user", "How long do I have to return it?", run.id),
        ("assistant", "You have 90 days.", run.id),
    ]
    messages = []
    for role, content, run_id in turns:
        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            run_id=run_id,
            role=role,
            content=content,
        )
        db.add(message)
        await db.flush()
        messages.append(message)
    answer = messages[-1]
    db.add(MessageRating(message_id=answer.id, user_id=ctx.user_id, rating=-1, comment=comment))
    await db.flush()
    return run, answer


async def test_a_question_already_asked_is_found_whatever_its_case_and_spacing(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    asked = await service.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(input="\nHow long is the\nreturn window?", reference_answer="30"),
    )
    await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="Lost receipt?", reference_answer="yes")
    )

    twins = await service.list_cases(
        ctx, dataset.id, same_input="  how LONG is the return   window? "
    )
    none = await service.list_cases(ctx, dataset.id, same_input="How long is the return window")

    assert [case.case_id for case in twins.items] == [asked.case_id]
    assert (twins.total, none.total) == (1, 0)


async def test_editing_a_case_mints_a_version_and_the_old_one_stays_readable(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    assert dataset.latest_version == 0

    first = await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="Return window?", reference_answer="yes")
    )
    second = await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="Lost receipt?", reference_answer="yes")
    )
    edited = await service.update_case(
        ctx,
        dataset.id,
        first.case_id,
        DatasetCaseUpdate(input="How long is the return window?", reference_answer="30 days"),
    )

    assert edited.case_id == first.case_id
    assert edited.id != first.id
    v2 = await service.list_cases(ctx, dataset.id, version=2)
    v3 = await service.list_cases(ctx, dataset.id)
    assert v3.version == 3
    assert [case.input for case in v2.items] == ["Return window?", "Lost receipt?"]
    assert [case.input for case in v3.items] == ["How long is the return window?", "Lost receipt?"]
    assert v3.items[0].reference_answer == "30 days"
    assert v3.items[1].id == second.id

    await service.remove_case(ctx, dataset.id, second.case_id)
    v4 = await service.list_cases(ctx, dataset.id)
    assert [case.case_id for case in v4.items] == [first.case_id]
    assert (await service.list_cases(ctx, dataset.id, version=3)).total == 2

    versions = await service.list_versions(ctx, dataset.id)
    assert [(v.number, v.change, v.case_count) for v in versions.items] == [
        (4, "remove", 1),
        (3, "edit", 2),
        (2, "add", 2),
        (1, "add", 1),
    ]
    stored = await service.read(ctx, dataset.id)
    assert (stored.latest_version, stored.case_count) == (4, 1)


async def test_stats_count_what_the_newest_version_tests_against(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    assert dataset.stats.with_reference == 0
    assert dataset.stats.by_source == {"manual": 0, "import": 0, "conversation": 0, "synthetic": 0}

    both = await service.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(
            input="q1",
            reference_answer="30 days",
            checks=[{"type": "contains", "value": "30"}],
            tags=["returns", "billing"],
        ),
    )
    await service.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(
            input="q2",
            counter_example="never",
            expected_tool_calls=[{"tool": "search"}],
            tags=["returns"],
        ),
    )
    await service.import_cases(
        ctx,
        dataset.id,
        content=b"input,counter_example,tags\nq3,no,refusal\nq4,no,returns\n",
        filename="x.csv",
        fmt=None,
    )
    # Only the newest version counts: the revision that still had its check and
    # its "returns" tag stays in the versions before this edit.
    await service.update_case(
        ctx, dataset.id, both.case_id, DatasetCaseUpdate(checks=[], tags=["billing"])
    )
    other = await service.create(ctx, DatasetCreate(name="empty"))

    listed = {item.name: item.stats for item in (await service.list_readable(ctx)).items}
    stats = listed["refunds"]
    assert (
        stats.with_reference,
        stats.with_counter_example,
        stats.with_tool_calls,
        stats.with_checks,
    ) == (1, 3, 1, 0)
    assert stats.by_source == {"manual": 2, "import": 2, "conversation": 0, "synthetic": 0}
    # q1 kept only its reference; q2 expects a call and has a counter-example,
    # and the two imported have only a counter-example, which the reference
    # comparison grades as it grades a reference answer.
    assert {
        (mix.checks, mix.tool_calls, mix.reference): mix.cases for mix in stats.expectation_mix
    } == {(False, False, True): 3, (False, True, True): 1}
    assert [(tag.tag, tag.cases) for tag in stats.top_tags] == [
        ("returns", 2),
        ("billing", 1),
        ("refusal", 1),
    ]
    assert listed["empty"].by_source["manual"] == 0
    assert (await service.read(ctx, dataset.id)).stats == stats
    assert (
        await service.update(ctx, other.id, DatasetUpdate(description="x"))
    ).stats.top_tags == []

    stranger = await _owner(db)
    assert (
        await dataset_repo.case_stats(db, [dataset.id], organization_id=stranger.organization_id)
        == {}
    )
    assert await dataset_repo.case_stats(db, [], organization_id=ctx.organization_id) == {}


async def test_a_version_number_the_dataset_never_reached_is_not_found(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="empty"))

    assert (await service.list_cases(ctx, dataset.id)).items == []
    with pytest.raises(NotFoundError):
        await service.list_cases(ctx, dataset.id, version=1)


async def test_a_case_the_newest_version_does_not_hold_cannot_be_edited(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    with pytest.raises(NotFoundError):
        await service.remove_case(ctx, dataset.id, uuid.uuid4())
    case = await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="q", reference_answer="yes")
    )
    await service.remove_case(ctx, dataset.id, case.case_id)
    with pytest.raises(NotFoundError):
        await service.update_case(ctx, dataset.id, case.case_id, DatasetCaseUpdate(input="again"))


async def test_an_edit_clearing_the_only_expectation_is_refused_and_mints_nothing(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    case = await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="q", reference_answer="a")
    )

    with pytest.raises(InvalidCaseError) as refused:
        await service.update_case(
            ctx, dataset.id, case.case_id, DatasetCaseUpdate(reference_answer=None, note="n")
        )
    assert [problem["field"] for problem in refused.value.details["fields"]] == ["reference_answer"]
    assert (await service.read(ctx, dataset.id)).latest_version == 1

    swapped = await service.update_case(
        ctx, dataset.id, case.case_id, DatasetCaseUpdate(reference_answer=None, counter_example="b")
    )
    assert (swapped.reference_answer, swapped.counter_example) == (None, "b")


async def test_a_hundred_csv_rows_import_as_one_version_and_export_unchanged(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="imported"))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for number in range(100):
        writer.writerow(
            [
                f"Question {number}, with a comma",
                '[{"role": "user", "content": "earlier"}]' if number % 2 else "",
                f"Answer {number}" if number % 3 else "",
                "'=not a formula" if number == 7 else "Never" if number % 3 == 0 else "",
                '[{"tool": "search", "args": {"q": "refund"}}]' if number % 5 == 0 else "",
                ("exact", "in_order", "any")[number % 3],
                '[{"type": "contains", "path": null, "value": "days"}]' if number % 6 == 0 else "",
                "billing,returns" if number % 2 else "",
                "line one\nline two" if number == 9 else "",
            ]
        )
    original = buffer.getvalue()

    version = await service.import_cases(
        ctx, dataset.id, content=original.encode(), filename="cases.csv", fmt=None
    )
    assert (version.number, version.change, version.changed_cases, version.case_count) == (
        1,
        "import",
        100,
        100,
    )
    exported = await service.export(ctx, dataset.id, version=None, fmt="csv")
    assert exported.row_count == 100
    assert exported.content == original

    jsonl = await service.export(ctx, dataset.id, version=1, fmt="jsonl")
    await service.import_cases(
        ctx, dataset.id, content=jsonl.content.encode(), filename="cases.jsonl", fmt=None
    )
    again = await service.list_cases(ctx, dataset.id, skip=100, limit=100)
    assert again.total == 200
    assert (await service.export(ctx, dataset.id, version=2, fmt="jsonl")).content == (
        jsonl.content * 2
    )
    sources = await db.scalars(
        select(DatasetCase.source).where(DatasetCase.dataset_id == dataset.id)
    )
    assert set(sources) == {"import"}


async def test_exporting_an_empty_dataset_is_the_header_alone_and_is_audited(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="empty"))

    result = await service.export(ctx, dataset.id, version=None, fmt="csv")

    assert result.content.strip() == ",".join(COLUMNS)
    assert result.filename.startswith("dataset_v0_export_")
    actions = await db.scalars(
        select(AppAdminAuditLog.action).where(AppAdminAuditLog.target_id == str(dataset.id))
    )
    assert "dataset.exported" in set(actions)


async def test_a_credential_in_a_case_is_redacted_before_it_is_stored(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="leaky"))
    key = "sk-ant-api03-" + "a" * 40

    case = await service.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(
            input=f"My key is {key}",
            history=[{"role": "user", "content": f"use {key}"}],
            note=f"seen {key}",
            expected_tool_calls=[{"tool": "login", "args": {"token": key, "n": 1, "all": [key]}}],
            checks=[{"type": "contains", "value": f"Bearer {key}", "nested": {"k": [key]}}],
            tags=[key],
        ),
    )

    stored = await db.get(DatasetCase, case.id)
    assert stored is not None
    text = (
        f"{stored.input} {stored.history} {stored.note} {stored.expected_tool_calls}"
        f" {stored.checks} {stored.tags}"
    )
    assert key not in text
    assert "[redacted:" in stored.input
    assert stored.expected_tool_calls[0]["args"]["n"] == 1
    assert stored.checks[0]["type"] == "contains"
    for fmt in ("csv", "jsonl"):
        exported = await service.export(ctx, dataset.id, version=None, fmt=fmt)
        assert key not in exported.content
    listed = await service.list_cases(ctx, dataset.id)
    assert key not in listed.model_dump_json()
    details = await db.scalar(
        select(AppAdminAuditLog.details).where(
            AppAdminAuditLog.action == "dataset.version_created",
            AppAdminAuditLog.target_id == str(dataset.id),
        )
    )
    assert details is not None
    assert details["redacted_secrets"] == 8


async def test_a_rated_down_answer_becomes_a_case_linked_to_its_run(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="from activity"))
    run, answer = await _rated_down_turn(db, ctx)

    case = await service.add_from_message(
        ctx, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
    )

    assert case.source == "conversation"
    assert case.source_run_id == run.id
    assert case.source_message_id == answer.id
    assert case.source_conversation_id == run.conversation_id
    assert case.input == "How long do I have to return it?"
    assert [turn.model_dump() for turn in case.history] == [
        {"role": "user", "content": "Hi, I bought a kettle"},
        {"role": "assistant", "content": "Hello! How can I help?"},
    ]
    assert case.counter_example == "You have 90 days."
    assert case.reference_answer is None
    assert case.note == "Wrong refund window"


async def test_an_answer_already_a_case_is_not_added_twice(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="from activity"))
    elsewhere = await service.create(ctx, DatasetCreate(name="another"))
    _, answer = await _rated_down_turn(db, ctx)
    first = await service.add_from_message(
        ctx, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
    )

    with pytest.raises(AlreadyExistsError) as refused:
        await service.add_from_message(
            ctx, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
        )
    other = await service.add_from_message(
        ctx, elsewhere.id, DatasetCaseFromMessage(message_id=answer.id)
    )
    await service.remove_case(ctx, dataset.id, first.case_id)
    again = await service.add_from_message(
        ctx, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
    )

    assert refused.value.details == {"case_id": first.case_id}
    assert other.source_message_id == again.source_message_id == answer.id


async def test_a_good_answer_can_be_kept_as_the_reference(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="good answers"))
    _, answer = await _rated_down_turn(db, ctx, comment=None)

    case = await service.add_from_message(
        ctx,
        dataset.id,
        DatasetCaseFromMessage(message_id=answer.id, answer_as="reference_answer"),
    )

    assert case.reference_answer == "You have 90 days."
    assert case.counter_example is None
    assert case.note is None


@pytest.mark.security
async def test_an_answer_from_another_organization_is_refused_as_missing(db) -> None:
    """The source must belong to the caller's organization - even for its owner."""
    ctx = await _owner(db)
    elsewhere = AuthContext(
        user_id=ctx.user_id,
        organization_id=(await _org(db, owner=await _user(db))).id,
        role=OrgRoleName.OWNER.value,
    )
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="mine"))
    _, foreign_answer = await _rated_down_turn(db, elsewhere)

    with pytest.raises(NotFoundError) as refused:
        await service.add_from_message(
            ctx, dataset.id, DatasetCaseFromMessage(message_id=foreign_answer.id)
        )
    with pytest.raises(NotFoundError) as missing:
        await service.add_from_message(
            ctx, dataset.id, DatasetCaseFromMessage(message_id=uuid.uuid4())
        )
    assert (refused.value.message, refused.value.details) == (
        "Message not found",
        {"message_id": foreign_answer.id},
    )
    assert missing.value.message == "Message not found"
    assert (await service.read(ctx, dataset.id)).case_count == 0


async def test_a_member_without_runs_view_needs_to_be_able_to_open_the_conversation(db) -> None:
    owner = await _owner(db)
    member = await _member(db, Organization(id=owner.organization_id), OrgRoleName.MEMBER)
    service = DatasetService(db)
    dataset = await service.create(member, DatasetCreate(name="members"))
    _, someone_elses = await _rated_down_turn(db, owner)
    _, their_own = await _rated_down_turn(db, member)

    with pytest.raises(NotFoundError):
        await service.add_from_message(
            member, dataset.id, DatasetCaseFromMessage(message_id=someone_elses.id)
        )
    case = await service.add_from_message(
        member, dataset.id, DatasetCaseFromMessage(message_id=their_own.id)
    )
    assert case.source_message_id == their_own.id


async def test_only_an_answer_with_a_question_before_it_can_become_a_case(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refusals"))
    run, answer = await _rated_down_turn(db, ctx)
    question = await db.scalar(
        select(Message).where(Message.run_id == run.id, Message.role == "user")
    )
    assert question is not None
    lonely = Message(
        id=uuid.uuid4(), conversation_id=answer.conversation_id, role="assistant", content="x"
    )
    other = Conversation(id=uuid.uuid4(), user_id=ctx.user_id, organization_id=ctx.organization_id)
    db.add(other)
    await db.flush()
    lonely.conversation_id = other.id
    db.add(lonely)
    await db.flush()

    with pytest.raises(BadRequestError):
        await service.add_from_message(
            ctx, dataset.id, DatasetCaseFromMessage(message_id=question.id)
        )
    with pytest.raises(BadRequestError):
        await service.add_from_message(
            ctx, dataset.id, DatasetCaseFromMessage(message_id=lonely.id)
        )
    silent = Conversation(id=uuid.uuid4(), user_id=ctx.user_id, organization_id=ctx.organization_id)
    db.add(silent)
    await db.flush()
    for role, content in (("user", "Anything?"), ("assistant", "  ")):
        db.add(Message(id=uuid.uuid4(), conversation_id=silent.id, role=role, content=content))
        await db.flush()
    blank = await db.scalar(
        select(Message).where(Message.conversation_id == silent.id, Message.role == "assistant")
    )
    assert blank is not None
    with pytest.raises(BadRequestError, match="no text to keep as a counter-example"):
        await service.add_from_message(ctx, dataset.id, DatasetCaseFromMessage(message_id=blank.id))
    with pytest.raises(BadRequestError, match="nor a tool call that changed something"):
        await service.add_from_message(
            ctx,
            dataset.id,
            DatasetCaseFromMessage(message_id=blank.id, answer_as="reference_answer"),
        )


async def _reply_in_steps(db, ctx: AuthContext, *, text: str | None) -> list[Message]:
    """A question, then a reply written as a step that called `write_memory`, then `text`."""
    conversation = Conversation(
        id=uuid.uuid4(), user_id=ctx.user_id, organization_id=ctx.organization_id
    )
    db.add(conversation)
    await db.flush()
    turns = [("user", "Remember I prefer email"), ("assistant", "")]
    if text is not None:
        turns.append(("assistant", text))
    messages = []
    for role, content in turns:
        message = Message(
            id=uuid.uuid4(), conversation_id=conversation.id, role=role, content=content
        )
        db.add(message)
        await db.flush()
        messages.append(message)
    db.add(
        ToolCall(
            message_id=messages[1].id,
            tool_call_id="call-1",
            tool_name="write_memory",
            args={"text": "prefers email"},
            started_at=_START,
            status="completed",
        )
    )
    await db.flush()
    return messages


async def test_a_reply_in_steps_is_one_case_whichever_step_is_added(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="steps"))
    bad = await service.create(ctx, DatasetCreate(name="bad steps"))
    _, step, said = await _reply_in_steps(db, ctx, text="Noted - email it is.")

    case = await service.add_from_message(
        ctx,
        dataset.id,
        DatasetCaseFromMessage(message_id=step.id, answer_as="reference_answer"),
    )
    with pytest.raises(AlreadyExistsError):
        await service.add_from_message(
            ctx,
            dataset.id,
            DatasetCaseFromMessage(message_id=said.id, answer_as="reference_answer"),
        )
    countered = await service.add_from_message(
        ctx, bad.id, DatasetCaseFromMessage(message_id=step.id)
    )

    assert case.input == "Remember I prefer email"
    assert case.reference_answer == "Noted - email it is."
    assert [call.model_dump() for call in case.expected_tool_calls] == [
        {"tool": "write_memory", "args": {}}
    ]
    assert case.source_message_id == said.id
    assert (countered.counter_example, countered.expected_tool_calls) == (
        "Noted - email it is.",
        [],
    )


async def test_a_reply_expects_only_the_calls_that_succeeded_and_changed_something(db) -> None:
    """A call the agent got wrong, or one that only read, is not what a good
    answer to the question has to do again."""
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="calls"))
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        version=1,
        spec={"name": "Clerk", "capabilities": [{"id": "memory_files"}]},
    )
    db.add(version)
    await db.flush()
    _, step, said = await _reply_in_steps(db, ctx, text="Noted - email it is.")
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=ctx.user_id,
        conversation_id=step.conversation_id,
        status="completed",
        started_at=_START,
    )
    db.add(run)
    await db.flush()
    step.run_id = said.run_id = run.id
    for number, (tool, status) in enumerate(
        (("read_memory", "completed"), ("write_memory", "failed")), start=2
    ):
        db.add(
            ToolCall(
                message_id=step.id,
                tool_call_id=f"call-{number}",
                tool_name=tool,
                args={},
                started_at=_START,
                status=status,
            )
        )
    await db.flush()

    case = await service.add_from_message(
        ctx,
        dataset.id,
        DatasetCaseFromMessage(message_id=step.id, answer_as="reference_answer"),
    )

    assert [call.tool for call in case.expected_tool_calls] == ["write_memory"]


async def test_a_reply_whose_agent_version_is_out_of_reach_keeps_every_call_that_succeeded(
    db,
) -> None:
    ctx = await _owner(db)
    elsewhere = await _org(db, owner=await _user(db))
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="calls"))
    foreign = Agent(
        id=uuid.uuid4(),
        organization_id=elsewhere.id,
        slug=f"other-{uuid.uuid4().hex[:8]}",
        name="Other",
        draft_spec={},
    )
    db.add(foreign)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=elsewhere.id,
        agent_id=foreign.id,
        version=1,
        spec={"name": "Other", "capabilities": [{"id": "memory_files"}]},
    )
    db.add(version)
    await db.flush()
    _, step = await _reply_in_steps(db, ctx, text=None)
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=foreign.id,
        agent_version_id=version.id,
        user_id=ctx.user_id,
        conversation_id=step.conversation_id,
        status="completed",
        started_at=_START,
    )
    db.add(run)
    await db.flush()
    step.run_id = run.id
    await db.flush()

    case = await service.add_from_message(
        ctx,
        dataset.id,
        DatasetCaseFromMessage(message_id=step.id, answer_as="reference_answer"),
    )

    assert [call.tool for call in case.expected_tool_calls] == ["write_memory"]


async def test_a_reply_with_only_tool_calls_is_kept_as_the_calls_it_expects(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="calls only"))
    _, step = await _reply_in_steps(db, ctx, text=None)

    case = await service.add_from_message(
        ctx,
        dataset.id,
        DatasetCaseFromMessage(message_id=step.id, answer_as="reference_answer"),
    )

    assert case.reference_answer is None
    assert [call.tool for call in case.expected_tool_calls] == ["write_memory"]


async def test_a_conversation_too_long_to_keep_is_refused(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="long"))
    _, answer = await _rated_down_turn(db, ctx)
    answer.content = "x" * 40_000
    await db.flush()

    with pytest.raises(BadRequestError):
        await service.add_from_message(
            ctx, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
        )


@pytest.mark.security
async def test_a_member_the_dataset_was_not_shared_with_cannot_read_or_change_it(db) -> None:
    owner = await _owner(db)
    org = Organization(id=owner.organization_id)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="private", visibility="private"))
    await service.add_case(owner, dataset.id, DatasetCaseCreate(input="q", reference_answer="yes"))

    for role in (OrgRoleName.MEMBER, OrgRoleName.VIEWER):
        outsider = await _member(db, org, role)
        with pytest.raises(NotFoundError):
            await service.read(outsider, dataset.id)
        with pytest.raises(NotFoundError):
            await service.list_cases(outsider, dataset.id)
        with pytest.raises(NotFoundError):
            await service.export(outsider, dataset.id, version=None, fmt="csv")
        with pytest.raises(NotFoundError):
            await service.add_case(
                outsider, dataset.id, DatasetCaseCreate(input="mine now", reference_answer="yes")
            )
        listing = await service.list_readable(outsider)
        assert dataset.id not in {item.id for item in listing.items}

    builder = await _member(db, org, OrgRoleName.BUILDER)
    assert (await service.read(builder, dataset.id)).can_edit is False
    with pytest.raises(NotFoundError):
        await service.add_case(
            builder, dataset.id, DatasetCaseCreate(input="mine now", reference_answer="yes")
        )


@pytest.mark.security
async def test_a_grant_widens_access_to_one_dataset_without_promoting_the_member(db) -> None:
    owner = await _owner(db)
    viewer = await _member(db, Organization(id=owner.organization_id), OrgRoleName.VIEWER)
    service = DatasetService(db)
    shared = await service.create(owner, DatasetCreate(name="shared", visibility="private"))
    other = await service.create(owner, DatasetCreate(name="other", visibility="private"))
    db.add(
        ResourceGrant(
            organization_id=owner.organization_id,
            subject_user_id=viewer.user_id,
            resource_type="dataset",
            resource_id=shared.id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()

    await service.add_case(
        viewer, shared.id, DatasetCaseCreate(input="from the viewer", reference_answer="yes")
    )
    listing = await service.list_readable(viewer)
    assert [(item.id, item.can_edit) for item in listing.items] == [(shared.id, True)]
    assert (await service.list_readable(viewer, shared_with_me=True)).total == 1
    with pytest.raises(NotFoundError):
        await service.read(viewer, other.id)


async def test_the_owner_lists_everything_and_shared_with_me_reads_the_grants(db) -> None:
    owner = await _owner(db)
    service = DatasetService(db)
    await service.create(owner, DatasetCreate(name="b", description="refund questions"))
    await service.create(owner, DatasetCreate(name="a"))

    everything = await service.list_readable(owner, sort="updated")
    assert everything.total == 2
    assert all(item.can_edit for item in everything.items)
    assert [i.name for i in (await service.list_readable(owner, search="refund")).items] == ["b"]
    assert (await service.list_readable(owner, shared_with_me=True)).total == 0


async def test_names_are_unique_per_organization_and_renaming_keeps_the_version(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    first = await service.create(ctx, DatasetCreate(name="refunds"))
    await service.add_case(ctx, first.id, DatasetCaseCreate(input="q", reference_answer="yes"))
    second = await service.create(ctx, DatasetCreate(name="returns"))

    with pytest.raises(AlreadyExistsError):
        await service.create(ctx, DatasetCreate(name="refunds"))
    with pytest.raises(AlreadyExistsError):
        await service.update(ctx, second.id, DatasetUpdate(name="refunds"))
    renamed = await service.update(ctx, first.id, DatasetUpdate(name="refund policy"))
    assert (renamed.name, renamed.latest_version) == ("refund policy", 1)
    same = await service.update(ctx, first.id, DatasetUpdate(name="refund policy"))
    assert same.name == "refund policy"

    elsewhere = await _owner(db)
    assert (await service.create(elsewhere, DatasetCreate(name="refunds"))).name == "refunds"
    db.add(Dataset(organization_id=ctx.organization_id, name="returns"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_deleting_a_dataset_takes_every_version_case_and_grant_with_it(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="doomed"))
    await service.add_case(ctx, dataset.id, DatasetCaseCreate(input="q", reference_answer="yes"))
    db.add(
        ResourceGrant(
            organization_id=ctx.organization_id,
            subject_user_id=(await _user(db)).id,
            resource_type="dataset",
            resource_id=dataset.id,
            level=GrantLevel.READ.value,
        )
    )
    await db.flush()

    await service.delete(ctx, dataset.id)

    for model in (DatasetVersion, DatasetCase):
        assert await db.scalar(select(func.count()).select_from(model)) == 0
    assert await db.scalar(select(func.count()).select_from(DatasetVersionCase)) == 0
    assert (
        await db.scalar(
            select(func.count())
            .select_from(ResourceGrant)
            .where(ResourceGrant.resource_id == dataset.id)
        )
        == 0
    )


async def test_a_version_number_is_unique_within_its_dataset(db) -> None:
    """The constraint is what a minting that skipped the lock would run into."""
    ctx = await _owner(db)
    dataset = await dataset_repo.create(
        db,
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="x",
        description=None,
        visibility="private",
    )
    for _ in range(2):
        db.add(
            DatasetVersion(
                dataset_id=dataset.id,
                organization_id=ctx.organization_id,
                number=1,
                case_count=0,
                change="add",
                changed_cases=0,
            )
        )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_case_source_outside_the_vocabulary_is_refused(db) -> None:
    ctx = await _owner(db)
    dataset = await dataset_repo.create(
        db,
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="x",
        description=None,
        visibility="private",
    )
    db.add(
        DatasetCase(
            dataset_id=dataset.id,
            organization_id=ctx.organization_id,
            case_id=uuid.uuid4(),
            input="q",
            source="scraped",
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_change_that_would_pass_the_case_ceiling_is_refused_whole(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dataset_service, "MAX_CASES", 2)
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="small"))
    await service.add_case(ctx, dataset.id, DatasetCaseCreate(input="one", reference_answer="yes"))

    with pytest.raises(BadRequestError):
        await service.import_cases(
            ctx,
            dataset.id,
            content=b"input,reference_answer\ntwo,a\nthree,a\n",
            filename="x.csv",
            fmt=None,
        )
    await service.add_case(ctx, dataset.id, DatasetCaseCreate(input="two", reference_answer="yes"))
    with pytest.raises(BadRequestError):
        await service.add_case(
            ctx, dataset.id, DatasetCaseCreate(input="three", reference_answer="yes")
        )
    assert (await service.read(ctx, dataset.id)).latest_version == 2


async def test_the_editable_listing_reaches_a_granted_dataset_however_old(db) -> None:
    """`editable=True` asks `resolve_access` of the whole listing, not of one page of it."""
    owner = await _owner(db)
    org = Organization(id=owner.organization_id)
    viewer = await _member(db, org, OrgRoleName.VIEWER)
    member = await _member(db, org, OrgRoleName.MEMBER)
    builder = await _member(db, org, OrgRoleName.BUILDER)
    service = DatasetService(db)
    granted = await service.create(
        owner, DatasetCreate(name="granted long ago", visibility="private")
    )
    read_only = await service.create(owner, DatasetCreate(name="read only", visibility="private"))
    for number in range(101):
        await service.create(owner, DatasetCreate(name=f"newer {number:03}", visibility="private"))
    await service.create(owner, DatasetCreate(name="org wide"))
    await service.create(member, DatasetCreate(name="the member's own", visibility="private"))
    for dataset_id, level in ((granted.id, GrantLevel.EDIT), (read_only.id, GrantLevel.READ)):
        db.add(
            ResourceGrant(
                organization_id=owner.organization_id,
                subject_user_id=viewer.user_id,
                resource_type="dataset",
                resource_id=dataset_id,
                level=level.value,
            )
        )
    await db.flush()

    def names(listing: DatasetList) -> list[str]:
        return [item.name for item in listing.items]

    viewer_editable = await service.list_readable(viewer, editable=True, limit=1)
    assert (names(viewer_editable), viewer_editable.total) == (["granted long ago"], 1)
    assert (await service.list_readable(viewer)).total == 3  # the two granted, and "org wide"

    assert names(await service.list_readable(member, editable=True)) == ["the member's own"]
    builder_editable = await service.list_readable(builder, editable=True, sort="name")
    assert names(builder_editable) == ["org wide"]
    assert (await service.list_readable(owner, editable=True)).total == 105
    # An admin's edit scope is the whole organization: no grant, and still every row.
    admin = await _member(db, org, OrgRoleName.ADMIN)
    admin_editable = await service.list_readable(admin, editable=True, search="the member")
    assert names(admin_editable) == ["the member's own"]
    assert (await service.list_readable(admin, editable=True, limit=1)).total == 105


@pytest.mark.security
async def test_the_runnable_datasets_are_the_ones_the_caller_may_run_with_a_case(db) -> None:
    """What decides Test draft, Start and Score against a case: one row, not every dataset."""
    owner = await _owner(db)
    service = DatasetService(db)
    case = DatasetCaseCreate(input="q", reference_answer="a")
    granted = await service.create(owner, DatasetCreate(name="granted", visibility="private"))
    await service.add_case(owner, granted.id, case)
    kept = await service.create(owner, DatasetCreate(name="not granted", visibility="private"))
    await service.add_case(owner, kept.id, case)
    await service.create(owner, DatasetCreate(name="empty"))
    viewer = await _member(db, Organization(id=owner.organization_id), OrgRoleName.VIEWER)
    db.add(
        ResourceGrant(
            organization_id=owner.organization_id,
            subject_user_id=viewer.user_id,
            resource_type="dataset",
            resource_id=granted.id,
            level=GrantLevel.USE.value,
        )
    )
    await db.flush()

    for_viewer = await service.list_readable(viewer, runnable=True, limit=1)
    for_owner = await service.list_readable(owner, runnable=True, sort="name")

    # A Viewer's role runs nothing; the grant on one dataset is the whole answer.
    assert ([item.name for item in for_viewer.items], for_viewer.total) == (["granted"], 1)
    # The owner runs every dataset - except one with no case to run.
    assert [item.name for item in for_owner.items] == ["granted", "not granted"]


@pytest.mark.parametrize("scope", list(Scope))
async def test_the_editable_predicate_admits_exactly_what_resolve_access_does(
    db, scope: Scope
) -> None:
    """The SQL arm and `_scope_allows` are two spellings of one rule; every row agrees."""
    owner = await _owner(db)
    other = await _user(db)
    rows = [
        Dataset(
            organization_id=owner.organization_id,
            owner_user_id=row_owner,
            visibility=visibility,
            name=f"{label}-{visibility}",
        )
        for label, row_owner in (("mine", owner.user_id), ("theirs", other.id), ("nobody", None))
        for visibility in ("private", "team", "org")
    ]
    db.add_all(rows)
    await db.flush()
    granted = rows[1].id

    admitted = set(
        await db.scalars(
            select(Dataset.id).where(
                Dataset.organization_id == owner.organization_id,
                reached_by_scope(
                    Dataset.owner_user_id,
                    Dataset.visibility,
                    Dataset.id,
                    scope=scope,
                    user_id=owner.user_id,
                    granted_ids=[granted],
                ),
            )
        )
    )
    expected = {
        row.id for row in rows if _scope_allows(scope, row, owner.user_id) or row.id == granted
    }
    assert admitted == expected


async def _every_shape(db, owner: AuthContext) -> list[Dataset]:
    """One dataset per owner - the caller, somebody else, nobody - and per visibility.

    In the order they are built: the caller's private, team and org rows, then
    somebody else's, then the ownerless ones.
    """
    other = await _user(db)
    rows = [
        Dataset(
            organization_id=owner.organization_id,
            owner_user_id=row_owner,
            visibility=visibility,
            name=f"{label}-{visibility}",
        )
        for label, row_owner in (("mine", owner.user_id), ("theirs", other.id), ("nobody", None))
        for visibility in ("private", "team", "org")
    ]
    db.add_all(rows)
    await db.flush()
    return rows


async def _admitted(db, owner: AuthContext, predicate: ColumnElement[bool]) -> set[uuid.UUID]:
    return set(
        await db.scalars(
            select(Dataset.id).where(Dataset.organization_id == owner.organization_id, predicate)
        )
    )


@pytest.mark.parametrize("scope", list(Scope))
async def test_the_editable_predicate_without_a_grant_admits_what_the_scope_alone_does(
    db, scope: Scope
) -> None:
    owner = await _owner(db)
    rows = await _every_shape(db, owner)

    admitted = await _admitted(
        db,
        owner,
        reached_by_scope(
            Dataset.owner_user_id,
            Dataset.visibility,
            Dataset.id,
            scope=scope,
            user_id=owner.user_id,
            granted_ids=[],
        ),
    )

    assert admitted == {row.id for row in rows if _scope_allows(scope, row, owner.user_id)}


@pytest.mark.parametrize("granting", [False, True])
async def test_the_visible_predicate_admits_what_a_shared_scope_or_a_grant_does(
    db, granting: bool
) -> None:
    """Own, org-visible or granted: `_scope_allows` at `shared`, and the grant beside it."""
    owner = await _owner(db)
    rows = await _every_shape(db, owner)
    # Somebody else's team row: nothing but a grant reaches it.
    granted = [rows[4].id] if granting else []

    admitted = await _admitted(
        db,
        owner,
        visible_to_caller(
            Dataset.owner_user_id,
            Dataset.visibility,
            Dataset.id,
            user_id=owner.user_id,
            shared_ids=granted,
        ),
    )

    expected = {
        row.id
        for row in rows
        if _scope_allows(Scope.SHARED, row, owner.user_id) or row.id in granted
    }
    assert admitted == expected
    assert (rows[4].id in admitted) is granting


@pytest.mark.parametrize("granting", [False, True])
async def test_the_shared_predicate_admits_what_is_visible_and_not_the_callers_own(
    db, granting: bool
) -> None:
    owner = await _owner(db)
    rows = await _every_shape(db, owner)
    # The caller's own team row, and an ownerless private one: a grant on the
    # first does not make it shared with them, and nobody's row is not theirs.
    granted = [rows[1].id, rows[6].id] if granting else []

    admitted = await _admitted(
        db,
        owner,
        shared_with_caller(
            Dataset.owner_user_id,
            Dataset.visibility,
            Dataset.id,
            user_id=owner.user_id,
            shared_ids=granted,
        ),
    )

    expected = {
        row.id
        for row in rows
        if (_scope_allows(Scope.SHARED, row, owner.user_id) or row.id in granted)
        and row.owner_user_id != owner.user_id
    }
    assert admitted == expected
    assert (rows[6].id in admitted) is granting


async def test_an_organization_past_its_stored_version_rows_is_refused(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ceiling sums every version of every dataset of one organization, and only it."""
    monkeypatch.setattr(dataset_service.settings, "DATASET_MAX_VERSION_ROWS_PER_ORG", 5)
    ctx = await _owner(db)
    service = DatasetService(db)
    first = await service.create(ctx, DatasetCreate(name="first"))
    second = await service.create(ctx, DatasetCreate(name="second"))
    case = DatasetCaseCreate(input="q", reference_answer="a")
    await service.add_case(ctx, first.id, case)  # v1 holds 1
    await service.add_case(ctx, first.id, case)  # v2 holds 2
    await service.add_case(ctx, second.id, case)  # v1 holds 1: 4 rows in all

    # Another organization's rows are its own: it still has room for its first five.
    stranger = await _owner(db)
    theirs = await service.create(stranger, DatasetCreate(name="theirs"))
    await service.add_case(stranger, theirs.id, case)
    await service.add_case(stranger, theirs.id, case)

    with pytest.raises(BadRequestError) as refused:
        await service.add_case(ctx, second.id, case)  # v2 would hold 2: 6 rows
    assert refused.value.details == {"version_rows": 4, "adding": 2, "max_version_rows": 5}
    assert "DATASET_MAX_VERSION_ROWS_PER_ORG" in refused.value.message
    assert (await service.read(ctx, second.id)).latest_version == 1
    assert await dataset_repo.version_rows(db, organization_id=ctx.organization_id) == 4
    assert await dataset_repo.version_rows(db, organization_id=stranger.organization_id) == 3

    await service.remove_case(
        ctx, first.id, (await service.list_cases(ctx, first.id)).items[0].case_id
    )
    assert await dataset_repo.version_rows(db, organization_id=ctx.organization_id) == 5


async def test_a_name_taken_by_a_concurrent_request_answers_409_not_500(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The name check is a read two requests can both pass; the constraint decides."""
    ctx = await _owner(db)
    service = DatasetService(db)
    await service.create(ctx, DatasetCreate(name="refunds"))
    other = await service.create(ctx, DatasetCreate(name="returns"))
    monkeypatch.setattr(dataset_repo, "get_by_name", AsyncMock(return_value=None))

    with pytest.raises(AlreadyExistsError):
        await service.create(ctx, DatasetCreate(name="refunds"))
    with pytest.raises(AlreadyExistsError):
        await service.update(ctx, other.id, DatasetUpdate(name="refunds"))
    assert {item.name for item in (await service.list_readable(ctx)).items} == {
        "refunds",
        "returns",
    }


async def test_an_order_mode_outside_the_three_is_refused_by_the_table(db) -> None:
    ctx = await _owner(db)
    dataset = await dataset_repo.create(
        db,
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="x",
        description=None,
        visibility="private",
    )
    db.add(
        DatasetCase(
            dataset_id=dataset.id,
            organization_id=ctx.organization_id,
            case_id=uuid.uuid4(),
            input="q",
            source="manual",
            order_mode="sorted",
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.security
async def test_a_version_read_with_another_tenant_finds_no_cases(db) -> None:
    """The case reads take the tenant too, so a version id alone reaches nothing."""
    ctx = await _owner(db)
    elsewhere = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="mine"))
    case = await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="q", reference_answer="yes")
    )
    version = await dataset_repo.get_version(db, dataset.id, 1, organization_id=ctx.organization_id)
    assert version is not None

    other = elsewhere.organization_id
    assert await dataset_repo.list_cases(db, version.id, organization_id=other) == []
    assert await dataset_repo.find_case(db, version.id, case.case_id, organization_id=other) is None
    assert await dataset_repo.last_position(db, version.id, organization_id=other) == -1


async def test_a_check_keeps_the_parameters_scoring_reads(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="checks"))
    schema = {"type": "object", "required": ["days"]}
    await service.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(input="q", checks=[{"type": "json_schema", "schema": schema}]),
    )
    stored = (await service.list_cases(ctx, dataset.id)).items[0].checks[0]
    assert stored.model_dump() == {"type": "json_schema", "schema": schema}


async def _case_with_an_older_check(db) -> tuple[AuthContext, DatasetService, uuid.UUID, uuid.UUID]:
    """A case whose stored check scoring no longer accepts, as one written earlier holds."""
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="older checks"))
    case = await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="q", reference_answer="a")
    )
    row = await db.get(DatasetCase, case.id)
    assert row is not None
    row.checks = [{"type": "rubric", "criteria": ["tone"], "scale": 5}]
    await db.flush()
    return ctx, service, dataset.id, case.case_id


async def test_a_stored_check_scoring_no_longer_knows_is_still_read(db) -> None:
    ctx, service, dataset_id, _ = await _case_with_an_older_check(db)

    stored = (await service.list_cases(ctx, dataset_id)).items[0].checks[0]

    assert stored.model_dump() == {"type": "rubric", "criteria": ["tone"], "scale": 5}


async def test_a_stored_check_scoring_no_longer_knows_still_exports(db) -> None:
    ctx, service, dataset_id, _ = await _case_with_an_older_check(db)

    exported = await service.export(ctx, dataset_id, version=None, fmt="jsonl")

    assert '"type": "rubric"' in exported.content


async def test_editing_another_field_keeps_a_check_scoring_no_longer_knows(db) -> None:
    ctx, service, dataset_id, case_id = await _case_with_an_older_check(db)

    edited = await service.update_case(ctx, dataset_id, case_id, DatasetCaseUpdate(note="n"))

    assert edited.note == "n"
    assert edited.checks[0].type == "rubric"


async def test_a_check_scoring_no_longer_knows_still_counts_as_what_a_case_expects(db) -> None:
    ctx, service, dataset_id, case_id = await _case_with_an_older_check(db)
    row = await db.scalar(select(DatasetCase).where(DatasetCase.case_id == case_id))
    assert row is not None
    row.reference_answer = None
    await db.flush()

    kept = await service.update_case(ctx, dataset_id, case_id, DatasetCaseUpdate(note="n"))
    assert (kept.reference_answer, kept.checks[0].type) == (None, "rubric")

    with pytest.raises(InvalidCaseError) as refused:
        await service.update_case(ctx, dataset_id, case_id, DatasetCaseUpdate(checks=[]))
    assert [problem["field"] for problem in refused.value.details["fields"]] == ["reference_answer"]


async def _case_from_someone(db) -> tuple[AuthContext, AuthContext, uuid.UUID]:
    """An owner's dataset holding a case taken from a member's rated-down answer."""
    owner = await _owner(db)
    member = await _member(db, Organization(id=owner.organization_id), OrgRoleName.MEMBER)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="from members"))
    _, answer = await _rated_down_turn(db, member)
    case = await service.add_from_message(
        owner, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
    )
    assert case.source_run_id is not None
    return owner, member, case.id


async def _unlinked(db, revision_id: uuid.UUID) -> DatasetCase:
    db.expire_all()
    stored = await db.get(DatasetCase, revision_id)
    assert stored is not None
    assert stored.input == "How long do I have to return it?"
    assert stored.counter_example == "You have 90 days."
    assert (stored.source_run_id, stored.source_conversation_id, stored.source_message_id) == (
        None,
        None,
        None,
    )
    return stored


@pytest.mark.security
async def test_deleting_the_conversation_keeps_the_case_but_not_where_it_came_from(db) -> None:
    """The run outlives its conversation, so its link is cleared by hand, not by a cascade."""
    _, member, revision_id = await _case_from_someone(db)
    stored = await db.get(DatasetCase, revision_id)
    assert stored is not None and stored.source_conversation_id is not None

    await ConversationService(db).delete_conversation(
        stored.source_conversation_id,
        organization_id=member.organization_id,
        user_id=member.user_id,
    )

    await _unlinked(db, revision_id)


@pytest.mark.security
async def test_deleting_a_project_keeps_a_case_from_a_chat_it_takes_but_not_the_link(db) -> None:
    """A project takes the chats nobody else can reach, and their run outlives them."""
    owner, _, revision_id = await _case_from_someone(db)
    stored = await db.get(DatasetCase, revision_id)
    assert stored is not None and stored.source_conversation_id is not None
    project = await project_repo.create(
        db,
        organization_id=owner.organization_id,
        owner_user_id=owner.user_id,
        name="Refunds",
        description="",
        instructions="",
        default_agent_id=None,
        backend="state",
        visibility="org",
    )
    chat = await db.get(Conversation, stored.source_conversation_id)
    assert chat is not None
    # Its starter's account is gone, so the project is the chat's only way in.
    chat.project_id, chat.user_id = project.id, None
    await db.flush()

    await ProjectService(db).delete(owner, project.id)

    await _unlinked(db, revision_id)
    assert await db.get(Conversation, chat.id) is None


@pytest.mark.security
async def test_erasing_the_person_keeps_the_case_with_no_link_back_to_them(db) -> None:
    owner, member, revision_id = await _case_from_someone(db)
    assert member.user_id is not None
    member_id = member.user_id

    await UserService(db).delete(member_id)

    stored = await _unlinked(db, revision_id)
    assert stored.created_by_user_id == owner.user_id
    assert stored.note == "Wrong refund window"


@pytest.mark.security
async def test_erasing_the_author_of_a_case_clears_who_wrote_it(db) -> None:
    owner = await _owner(db)
    builder = await _member(db, Organization(id=owner.organization_id), OrgRoleName.BUILDER)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="shared", visibility="private"))
    db.add(
        ResourceGrant(
            organization_id=owner.organization_id,
            subject_user_id=builder.user_id,
            resource_type="dataset",
            resource_id=dataset.id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()
    case = await service.add_case(
        builder, dataset.id, DatasetCaseCreate(input="q", reference_answer="yes")
    )
    assert builder.user_id is not None

    await UserService(db).delete(builder.user_id)

    db.expire_all()
    stored = await db.get(DatasetCase, case.id)
    version = await dataset_repo.get_version(
        db, dataset.id, 1, organization_id=owner.organization_id
    )
    assert stored is not None and version is not None
    assert (stored.input, stored.created_by_user_id, version.created_by_user_id) == (
        "q",
        None,
        None,
    )


async def test_a_new_dataset_is_the_organization_s_unless_it_starts_private(db) -> None:
    """Datasets are shared test material: a team member finds one without being sent it."""
    owner = await _owner(db)
    member = await _member(db, Organization(id=owner.organization_id), OrgRoleName.MEMBER)
    service = DatasetService(db)
    shared = await service.create(owner, DatasetCreate(name="refunds"))
    kept = await service.create(owner, DatasetCreate(name="drafts", visibility="private"))

    listed = {item.id for item in (await service.list_readable(member)).items}

    assert shared.visibility == "org"
    assert (shared.id in listed, kept.id in listed) == (True, False)


async def test_a_link_opens_one_case_as_its_version_holds_it(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    first = await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="Return window?", reference_answer="yes")
    )
    await service.update_case(
        ctx, dataset.id, first.case_id, DatasetCaseUpdate(input="How long?", reference_answer="30")
    )

    newest = await service.read_case(ctx, dataset.id, first.case_id)
    older = await service.read_case(ctx, dataset.id, first.case_id, version=1)

    assert (newest.input, older.input) == ("How long?", "Return window?")
    with pytest.raises(NotFoundError):
        await service.read_case(ctx, dataset.id, uuid.uuid4())


@pytest.mark.security
async def test_whether_the_caller_may_run_a_dataset_is_read_per_dataset(db) -> None:
    """What the eval start dialog offers: a read grant shows a dataset but runs nothing."""
    owner = await _owner(db)
    member = await _member(db, Organization(id=owner.organization_id), OrgRoleName.MEMBER)
    service = DatasetService(db)
    readable = await service.create(owner, DatasetCreate(name="readable", visibility="private"))
    usable = await service.create(owner, DatasetCreate(name="usable", visibility="private"))
    for dataset_id, level in ((readable.id, GrantLevel.READ), (usable.id, GrantLevel.USE)):
        db.add(
            ResourceGrant(
                organization_id=owner.organization_id,
                subject_user_id=member.user_id,
                resource_type="dataset",
                resource_id=dataset_id,
                level=level.value,
            )
        )
    await db.flush()

    listed = await service.list_readable(member, sort="name")
    assert [(item.name, item.can_run) for item in listed.items] == [
        ("readable", False),
        ("usable", True),
    ]
    assert (await service.read(member, readable.id)).can_run is False
    assert (await service.read(member, usable.id)).can_run is True
    assert (await service.read(owner, readable.id)).can_run is True
