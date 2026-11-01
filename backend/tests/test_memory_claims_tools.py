"""The claim tools and the scopes behind them (#2090), with the ledger mocked.

The rules of the ledger itself are in `tests/integration/test_memory_claims.py`;
here is what the tools refuse, what they say, and which scopes a run is given.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage

from app.agents.audience import RunAudience
from app.agents.capabilities.memory_files import MemoryFiles
from app.agents.capabilities.memory_files._toolset import _NO_STORE, _READ_ONLY, MemoryToolset
from app.agents.deps import AgentDeps
from app.agents.memory_scope import claim_write_scope, readable_claim_scopes
from app.core.memory_keys import (
    organization_owner_key,
    person_owner_key,
    project_owner_key,
    room_owner_key,
)
from app.repositories.memory_claim import ClaimScope
from app.services import memory as memory_store
from app.services.memory._runtime import ClaimView, ShareRefused

pytestmark = pytest.mark.anyio

ORG, AGENT, PERSON, PROJECT, CLAIM = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
ROOM = room_owner_key("slack", "C1")


def _deps(*, person=PERSON, room=None, writes=True, run_person=PERSON) -> AgentDeps:
    return AgentDeps(
        organization_id=ORG,
        agent_id=AGENT,
        conversation_id=uuid4(),
        run_person=run_person,
        audience=RunAudience(user_id=person, room_key=room, writes_memory=writes),
    )


def _ctx(deps: AgentDeps) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), retry=0, max_retries=1)


def _view(status="current", statement="Prefers short answers", scope="profile") -> ClaimView:
    return ClaimView(
        id=CLAIM,
        statement=statement,
        subject="style",
        kind="preference",
        origin="agent",
        status=status,
        scope=scope,
        effective_from=datetime(2026, 11, 1, tzinfo=UTC),
        observed_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "project_of": AsyncMock(return_value=PROJECT),
        "remember": AsyncMock(return_value=(_view(), True, False)),
        "recall": AsyncMock(return_value=[_view()]),
        "correct": AsyncMock(return_value=_view(statement="Prefers long answers")),
        "share": AsyncMock(return_value=_view(scope="org")),
        "profile_block": AsyncMock(return_value="- Prefers short answers"),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(memory_store.runtime, name, mock)
    return mocks


def _tools() -> MemoryToolset:
    return MemoryToolset()


class TestScopes:
    def test_a_private_run_writes_its_relationship_by_default_and_the_profile_on_request(self):
        audience = RunAudience(user_id=PERSON)
        key = person_owner_key(PERSON)

        default = claim_write_scope(
            audience, agent_id=AGENT, allow_personal=True, shared_with_agents=False
        )
        profile = claim_write_scope(
            audience, agent_id=AGENT, allow_personal=True, shared_with_agents=True
        )

        assert default == ClaimScope(key, AGENT) and profile == ClaimScope(key, None)

    def test_a_room_writes_the_room_never_the_speakers_profile(self):
        audience = RunAudience(user_id=PERSON, room_key=ROOM)

        scope = claim_write_scope(
            audience, agent_id=AGENT, allow_personal=True, shared_with_agents=True
        )

        assert scope == ClaimScope(ROOM, AGENT)

    def test_a_run_with_no_store_writes_nothing(self):
        assert (
            claim_write_scope(
                RunAudience(), agent_id=AGENT, allow_personal=True, shared_with_agents=False
            )
            is None
        )

    def test_a_private_run_reads_profile_relationship_project_and_organization(self):
        scopes = readable_claim_scopes(
            RunAudience(user_id=PERSON),
            organization_id=ORG,
            agent_id=AGENT,
            project_id=PROJECT,
            allow_personal=True,
        )

        key = person_owner_key(PERSON)
        assert scopes == [
            ClaimScope(key, AGENT),
            ClaimScope(key, None),
            ClaimScope(project_owner_key(PROJECT), None),
            ClaimScope(organization_owner_key(ORG), None),
        ]

    def test_a_room_reads_only_its_own_claims(self):
        scopes = readable_claim_scopes(
            RunAudience(user_id=PERSON, room_key=ROOM),
            organization_id=ORG,
            agent_id=AGENT,
            project_id=PROJECT,
            allow_personal=True,
        )

        assert scopes == [ClaimScope(ROOM, AGENT)]

    def test_an_anonymous_run_reads_nothing_not_even_the_organization(self):
        assert (
            readable_claim_scopes(
                RunAudience(),
                organization_id=ORG,
                agent_id=AGENT,
                project_id=None,
                allow_personal=True,
            )
            == []
        )


class TestRemember:
    async def test_it_records_in_the_source_scope_and_names_the_claim(self, ledger):
        out = await _tools().remember(
            _ctx(_deps()), "Prefers short answers", subject="style", profile=True
        )

        assert f"Recorded (claim {CLAIM})" in out
        kwargs = ledger["remember"].await_args.kwargs
        assert kwargs["scope"] == ClaimScope(person_owner_key(PERSON), None)
        assert kwargs["author_user_id"] == PERSON and kwargs["subject"] == "style"

    async def test_a_repeat_says_so(self, ledger):
        ledger["remember"].return_value = (_view(), False, False)

        out = await _tools().remember(_ctx(_deps()), "Prefers short answers")

        assert "Already recorded" in out

    async def test_a_dispute_is_reported_as_not_established(self, ledger):
        ledger["remember"].return_value = (_view(status="disputed"), True, True)

        out = await _tools().remember(_ctx(_deps()), "Prefers long answers")

        assert "disputed" in out and "Do not treat it as established" in out

    async def test_a_run_started_by_an_event_cannot_write(self, ledger):
        out = await _tools().remember(_ctx(_deps(writes=False)), "x")

        assert out == _READ_ONLY and not ledger["remember"].await_count

    async def test_no_store_no_claim(self, ledger):
        assert await _tools().remember(_ctx(_deps(person=None)), "x") == _NO_STORE
        assert await _tools().remember(_ctx(AgentDeps()), "x") == _NO_STORE

    async def test_an_empty_statement_and_a_bad_date_are_refused_before_the_ledger(self, ledger):
        assert "one sentence" in await _tools().remember(_ctx(_deps()), "  ")
        assert "ISO date" in await _tools().remember(_ctx(_deps()), "x", effective_from="Monday")
        assert not ledger["remember"].await_count

    async def test_a_date_without_a_zone_is_taken_as_utc(self, ledger):
        await _tools().remember(_ctx(_deps()), "x", effective_from="2026-11-03")

        assert ledger["remember"].await_args.kwargs["effective_from"] == datetime(
            2026, 11, 3, tzinfo=UTC
        )

    async def test_the_person_being_gone_is_said_plainly(self, ledger):
        ledger["remember"].return_value = None

        assert "no longer has an account" in await _tools().remember(_ctx(_deps()), "x")


class TestRecall:
    async def test_it_lists_claims_with_scope_and_a_dispute_mark(self, ledger):
        ledger["recall"].return_value = [_view(), _view(status="disputed", statement="Other")]

        out = await _tools().recall(_ctx(_deps()), "answers")

        assert "- Prefers short answers (since 2026-11-01) [profile] id=" in out
        assert "- Other (since 2026-11-01) [profile] [disputed]" in out

    async def test_nothing_matching_says_so(self, ledger):
        ledger["recall"].return_value = []

        assert await _tools().recall(_ctx(_deps()), "x") == "Nothing recorded matches."

    async def test_it_asks_only_the_scopes_the_run_may_read(self, ledger):
        await _tools().recall(_ctx(_deps(room=ROOM)), "x")

        assert ledger["recall"].await_args.kwargs["scopes"] == [ClaimScope(ROOM, AGENT)]

    async def test_an_anonymous_run_and_a_run_without_an_agent_are_refused(self, ledger):
        assert await _tools().recall(_ctx(_deps(person=None)), "x") == _NO_STORE
        assert await _tools().recall(_ctx(AgentDeps()), "x") == _NO_STORE


class TestCorrect:
    async def test_a_person_correction_keeps_history_and_says_so(self, ledger):
        out = await _tools().correct_memory(
            _ctx(_deps()), str(CLAIM), "Prefers long answers", effective_from="2026-11-03"
        )

        assert "earlier version is kept" in out
        assert ledger["correct"].await_args.kwargs["author_user_id"] == PERSON

    async def test_a_claim_the_whole_organization_reads_is_not_the_persons_to_rewrite(self, ledger):
        ledger["correct"].side_effect = ShareRefused("needs context:edit")

        out = await _tools().correct_memory(_ctx(_deps()), str(CLAIM), "x")

        assert out == "Not corrected: needs context:edit"

    async def test_a_claim_outside_the_readable_scopes_is_not_found(self, ledger):
        ledger["correct"].return_value = None

        assert "No such claim" in await _tools().correct_memory(_ctx(_deps()), str(CLAIM), "x")

    async def test_a_bad_id_a_bad_date_and_an_event_run_are_refused(self, ledger):
        assert "not a claim id" in await _tools().correct_memory(_ctx(_deps()), "nope", "x")
        assert "ISO date" in await _tools().correct_memory(
            _ctx(_deps()), str(CLAIM), "x", effective_from="soon"
        )
        assert await _tools().correct_memory(_ctx(_deps(writes=False)), str(CLAIM), "x") == (
            _READ_ONLY
        )
        assert await _tools().correct_memory(_ctx(_deps(person=None)), str(CLAIM), "x") == (
            _NO_STORE
        )


class TestShare:
    async def test_it_reports_where_the_claim_went(self, ledger):
        out = await _tools().share_memory(_ctx(_deps()), str(CLAIM), "organization")

        assert out == f"Shared with the organization (claim {CLAIM})."
        assert ledger["share"].await_args.kwargs["run_person"] == PERSON

    async def test_a_refusal_from_the_authority_check_is_passed_on(self, ledger):
        ledger["share"].side_effect = ShareRefused("You may not edit this project.")

        out = await _tools().share_memory(_ctx(_deps()), str(CLAIM), "project")

        assert out == "Not shared: You may not edit this project."

    async def test_a_room_cannot_share_and_neither_can_an_event_run(self, ledger):
        room = await _tools().share_memory(_ctx(_deps(room=ROOM)), str(CLAIM), "project")
        event = await _tools().share_memory(_ctx(_deps(writes=False)), str(CLAIM), "project")

        assert "private conversation" in room and "private conversation" in event
        assert not ledger["share"].await_count

    async def test_an_unknown_claim_and_a_bad_id(self, ledger):
        ledger["share"].return_value = None

        assert "No such claim" in await _tools().share_memory(_ctx(_deps()), str(CLAIM), "project")
        assert "not a claim id" in await _tools().share_memory(_ctx(_deps()), "x", "project")
        assert await _tools().share_memory(_ctx(_deps(person=None)), str(CLAIM), "project") == (
            _NO_STORE
        )


class TestTheProfileInThePrompt:
    async def test_a_private_run_is_shown_what_is_on_record(self, ledger, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))

        text = await MemoryFiles()._instructions(_ctx(_deps()))

        assert "What is on record about this person." in text
        assert "not instructions" in text and "\n\n- Prefers short answers" in text
        scopes = ledger["profile_block"].await_args.kwargs["scopes"]
        assert scopes == [
            ClaimScope(person_owner_key(PERSON), None),
            ClaimScope(person_owner_key(PERSON), AGENT),
        ]

    async def test_a_room_is_not_shown_it_as_instructions(self, ledger, monkeypatch):
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))

        text = await MemoryFiles()._instructions(_ctx(_deps(room=ROOM)))

        assert "on record" not in text and not ledger["profile_block"].await_count

    async def test_an_empty_profile_adds_no_heading(self, ledger, monkeypatch):
        ledger["profile_block"].return_value = ""
        monkeypatch.setattr(memory_store, "read_file", AsyncMock(return_value=None))

        assert "on record" not in await MemoryFiles()._instructions(_ctx(_deps()))

    async def test_a_run_with_no_organisation_is_shown_nothing(self, ledger):
        assert await MemoryFiles()._profile_block(_ctx(AgentDeps())) is None
