"""The re-sent tool output report over real rows: one organization, sizes and counts only.

It reads tool results and run manifests, which hold what a model was sent, so the
two things it may never do are read another organization's rows and print any of
that content.
"""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.run_manifest import RunManifest
from app.db.models.user import User
from app.services.tool_output_report import ToolOutputReportService, as_json, render_text

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_NOW = datetime.now(UTC)
_TODAY = _NOW.date()
SECRET_RESULT = "TOP-SECRET-RESULT"
SECRET_PROMPT = "TOP-SECRET-PROMPT"


async def _owner(db) -> User:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _org(db, owner: User) -> Organization:
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    return organization


async def _agent(db, organization: Organization, owner: User, name: str, capabilities=()) -> Agent:
    spec = AgentSpec(name=name).model_dump(mode="json")
    spec["capabilities"] = list(capabilities)
    agent = Agent(
        organization_id=organization.id,
        owner_user_id=owner.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        draft_spec=spec,
        visibility=Visibility.ORG.value,
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(agent_id=agent.id, organization_id=organization.id, version=1, spec=spec)
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    await db.flush()
    return agent


async def _run(
    db,
    agent: Agent,
    owner: User,
    *,
    results: dict[str, int],
    requests: list[tuple[int, list[str]]] | None,
    input_tokens: int = 0,
    parent: AgentRun | None = None,
    started_at: datetime = _NOW,
    **extra,
) -> AgentRun:
    """A run with one assistant turn calling `results` and, unless None, a manifest."""
    run = AgentRun(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        agent_version_id=agent.current_version_id,
        status="completed",
        surface=extra.pop("surface", RunSurface.WEB.value),
        started_at=started_at,
        input_tokens=input_tokens,
        parent_run_id=parent.id if parent else None,
        **extra,
    )
    db.add(run)
    await db.flush()
    conversation = Conversation(organization_id=agent.organization_id, user_id=owner.id)
    db.add(conversation)
    await db.flush()
    message = Message(
        conversation_id=conversation.id, role="assistant", content="done", run_id=run.id
    )
    db.add(message)
    await db.flush()
    for name, size in results.items():
        db.add(
            ToolCall(
                message_id=message.id,
                tool_call_id=uuid.uuid4().hex,
                tool_name=name,
                args={},
                result=(SECRET_RESULT + "x" * size)[:size],
                status="completed",
                started_at=started_at,
            )
        )
    if requests is not None:
        db.add(
            RunManifest(
                run_id=run.id,
                organization_id=agent.organization_id,
                payload={
                    "instructions": SECRET_PROMPT,
                    "messages": [{"content": SECRET_PROMPT}],
                    "requests": [
                        {
                            "index": index,
                            "input_tokens": tokens,
                            "cache_read_tokens": 7,
                            "cache_write_tokens": 3,
                            "tool_calls": calls,
                            "model": "stub",
                        }
                        for index, (tokens, calls) in enumerate(requests)
                    ],
                },
                truncated=False,
            )
        )
    await db.flush()
    return run


async def _report(db, organization: Organization, **options):
    return await ToolOutputReportService(db).build(
        organization.id,
        started_from=options.pop("started_from", _TODAY - timedelta(days=1)),
        ended=options.pop("ended", _TODAY + timedelta(days=1)),
        **options,
    )


async def test_only_the_organizations_own_runs_are_measured(db) -> None:
    owner = await _owner(db)
    ours, theirs = await _org(db, owner), await _org(db, owner)
    support = await _agent(db, ours, owner, "Support")
    elsewhere = await _agent(db, theirs, owner, "Elsewhere")
    await _run(db, support, owner, results={"search": 400}, requests=[(100, ["search"]), (200, [])])
    await _run(
        db, elsewhere, owner, results={"fetch": 9_000}, requests=[(900, ["fetch"]), (900, [])]
    )

    report = await _report(db, ours)

    assert (report.runs, report.tool_calls) == (1, 1)
    assert [row.agent for row in report.resend] == ["Support"]
    assert [row.name for row in report.by_tool] == ["search"]
    assert report.resend[0].own_input_tokens == 300


async def test_a_delegate_is_measured_as_its_own_run_never_added_to_its_parent(db) -> None:
    owner = await _owner(db)
    organization = await _org(db, owner)
    lead, helper = (
        await _agent(db, organization, owner, "Lead"),
        await _agent(db, organization, owner, "Helper"),
    )
    # The parent's row adds its delegate's spend in; its manifest is its own requests.
    parent = await _run(
        db,
        lead,
        owner,
        results={"delegate": 100},
        requests=[(600, ["delegate"]), (400, [])],
        input_tokens=1_500,
    )
    await _run(
        db,
        helper,
        owner,
        results={"read": 2_000},
        requests=[(200, ["read"]), (300, [])],
        input_tokens=500,
        parent=parent,
    )

    report = await _report(db, organization)

    rows = {row.agent: row for row in report.resend}
    assert rows["Lead"].own_input_tokens == 1_000
    assert rows["Helper"].own_input_tokens == 500
    assert sum(row.own_input_tokens for row in report.resend) == 1_500
    assert rows["Helper"].resent_tokens == 2_000 // 4
    assert rows["Lead"].resent_tokens == 100 // 4


async def test_eval_and_builder_test_runs_are_left_out_unless_asked_for(db) -> None:
    owner = await _owner(db)
    organization = await _org(db, owner)
    support = await _agent(db, organization, owner, "Support")
    await _run(db, support, owner, results={}, requests=[(1, [])])
    await _run(db, support, owner, results={}, requests=[(1, [])], surface=RunSurface.EVAL.value)
    await _run(db, support, owner, results={}, requests=[(1, [])], is_test=True)

    assert (await _report(db, organization)).runs == 1
    assert (await _report(db, organization, include_eval=True)).runs == 2
    assert (await _report(db, organization, include_eval=True, include_tests=True)).runs == 3


async def test_a_window_with_no_runs_says_so(db) -> None:
    owner = await _owner(db)
    organization = await _org(db, owner)
    support = await _agent(db, organization, owner, "Support")
    await _run(
        db, support, owner, results={"search": 10}, requests=[(1, ["search"])], started_at=_NOW
    )

    report = await _report(db, organization, started_from=date(2020, 1, 1), ended=date(2020, 1, 31))

    assert report.runs == 0
    assert "No runs in this window." in render_text(report)


async def test_a_run_without_a_manifest_is_counted_but_not_estimated(db) -> None:
    owner = await _owner(db)
    organization = await _org(db, owner)
    support = await _agent(db, organization, owner, "Support")
    await _run(db, support, owner, results={"search": 700}, requests=None)

    report = await _report(db, organization)

    assert (report.runs, report.runs_with_manifest) == (1, 0)
    assert report.matching.without_manifest == 1
    assert report.by_tool[0].sizes.max == 700
    assert report.resend[0].share is None


async def test_bindings_come_from_the_version_the_run_served(db) -> None:
    owner = await _owner(db)
    organization = await _org(db, owner)
    coder = await _agent(
        db,
        organization,
        owner,
        "Coder",
        capabilities=[
            {"id": "tool_output_limits", "config": {"action": "truncate"}},
            {"id": "compaction", "config": {"strategy": "tiered"}},
        ],
    )
    await _run(
        db,
        coder,
        owner,
        results={"read": 30_000},
        requests=[(100, ["read"]), (100, []), (100, []), (100, []), (100, [])],
    )

    report = await _report(db, organization)

    row = report.resend[0]
    assert (row.tool_output_limits, row.compaction, row.overstated) == ("truncate", "tiered", True)
    assert (row.cache_read_tokens, row.cache_write_tokens) == (35, 15)
    assert row.saving_tokens["1.3 KB"] == round((30_000 - 1_300) * 2 / 4)


async def test_nothing_a_model_was_sent_reaches_the_report(db) -> None:
    owner = await _owner(db)
    organization = await _org(db, owner)
    support = await _agent(db, organization, owner, "Support")
    await _run(
        db, support, owner, results={"search": 5_000}, requests=[(100, ["search"]), (100, [])]
    )

    report = await _report(db, organization)
    printed = render_text(report) + json.dumps(as_json(report))

    assert report.tool_calls == 1
    assert SECRET_RESULT not in printed
    assert SECRET_PROMPT not in printed


async def test_an_organization_that_does_not_exist_is_refused(db) -> None:
    with pytest.raises(NotFoundError):
        await ToolOutputReportService(db).build(uuid.uuid4(), started_from=_TODAY, ended=_TODAY)
