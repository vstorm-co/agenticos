"""Tests for the skill-proposal repository.

A repository's behaviour *is* the statement it builds, so these read the
statement back. Two predicates matter.

`organization_id`, because applying a proposal writes a skill and a skill is
instructions every bound agent follows - a lookup without the tenant would let
one organization's reviewer accept another's.

And the key `get_pending_for_skill` uses: a stored skill is matched by id, one the
agent invented by name, because a new skill has no id until somebody accepts it.
Getting that wrong gives a reviewer one proposal per turn instead of one per
edit.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.skill_proposal import ProposalStatus, SkillProposal
from app.repositories import skill_proposal_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[SkillProposal] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0) if self._results else MagicMock()

    def add(self, instance: SkillProposal) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: SkillProposal) -> None:
        pass


def _filters(session: _RecordingSession) -> dict[str, object]:
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


def _scalar(value: object):
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _scalars(values: list[object]):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    result.scalars.return_value.first.return_value = values[0] if values else None
    return result


def _proposal(**overrides: object) -> SkillProposal:
    row = SkillProposal(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        skill_id=uuid.uuid4(),
        name="refunds",
        description="How refunds work.",
        content="Ask for the id.",
        resources={},
        status=ProposalStatus.PENDING.value,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


class TestReading:
    async def test_a_proposal_is_looked_up_inside_its_organization(self):
        organization_id, proposal_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await skill_proposal_repo.get(session, proposal_id, organization_id=organization_id)

        assert set(_filters(session).values()) >= {organization_id, proposal_id}

    async def test_a_pending_edit_is_matched_by_the_skill_it_edits(self):
        skill_id = uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await skill_proposal_repo.get_pending_for_skill(
            session, organization_id=uuid.uuid4(), skill_id=skill_id, name="refunds"
        )

        assert skill_id in _filters(session).values()
        assert "refunds" not in _filters(session).values()

    async def test_a_pending_new_skill_is_matched_by_name_because_it_has_no_id(self):
        session = _RecordingSession(_scalars([]))

        await skill_proposal_repo.get_pending_for_skill(
            session, organization_id=uuid.uuid4(), skill_id=None, name="escalation"
        )

        assert "escalation" in _filters(session).values()
        assert "IS NULL" in str(session.statements[-1])

    async def test_a_listing_is_newest_first_and_may_be_filtered(self):
        organization_id = uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await skill_proposal_repo.list_for_organization(
            session, organization_id=organization_id, status="pending"
        )

        statement = str(session.statements[-1])
        assert set(_filters(session).values()) >= {organization_id, "pending"}
        assert "ORDER BY" in statement
        assert "DESC" in statement

    async def test_an_unfiltered_listing_names_no_status(self):
        session = _RecordingSession(_scalars([]))

        await skill_proposal_repo.list_for_organization(session, organization_id=uuid.uuid4())

        assert "pending" not in _filters(session).values()


class TestWriting:
    async def test_creating_records_where_the_change_came_from(self):
        """The conversation especially: it is most of what makes the decision
        possible, because the same edit means different things asked by a lead
        and inferred from one complaint."""
        session = _RecordingSession()
        organization_id, skill_id, agent_id, conversation_id = (
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )

        await skill_proposal_repo.create(
            session,
            organization_id=organization_id,
            skill_id=skill_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            name="refunds",
            description="How refunds work now.",
            content="Ask for the receipt.",
            resources={"a.md": "one"},
        )

        [created] = session.added
        assert created.organization_id == organization_id
        assert created.skill_id == skill_id
        assert created.agent_id == agent_id
        assert created.conversation_id == conversation_id
        assert created.resources == {"a.md": "one"}

    async def test_replacing_a_body_keeps_the_row_a_reviewer_is_looking_at(self):
        session = _RecordingSession()
        row = _proposal()

        replaced = await skill_proposal_repo.replace_body(
            session,
            proposal=row,
            description="Newer.",
            content="Newer still.",
            resources={"b.md": "two"},
            conversation_id=None,
        )

        assert replaced is row
        assert replaced.description == "Newer."
        assert replaced.resources == {"b.md": "two"}

    async def test_deciding_records_who_and_when(self):
        """Without the timestamp there is no telling a decision made in review
        from one made six weeks later."""
        session = _RecordingSession()
        row = _proposal()
        reviewer = uuid.uuid4()

        decided = await skill_proposal_repo.decide(
            session, proposal=row, status=ProposalStatus.APPLIED, decided_by=reviewer
        )

        assert decided.status == "applied"
        assert decided.decided_by_user_id == reviewer
        assert decided.decided_at is not None


def test_a_proposal_says_what_it_is_and_where_it_stands():
    text = repr(_proposal())

    assert "refunds" in text
    assert "pending" in text
