"""Deciding what an agent wrote to a skill.

The refusals carry the feature.

*A change is never applied by the agent that wrote it.* A skill is instructions
every bound agent follows on every run, so an agent editing one directly would be
an agent rewriting what another agent does inside a conversation nobody reviewed.

*A decision is final.* Applying twice bumps a version against a body already
stored; discarding something applied tells a reader it never landed.

*Recording never breaks a run.* It happens in the same `finally` that records what
the run cost, so a name taken since must not replace the run's own outcome.

*One edit session is one proposal.* Three turns refining a checklist should leave
a reviewer one decision, not three copies of it.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.skill_proposal import ProposalStatus
from app.repositories import skill_proposal_repo
from app.services.skill_proposal import SkillProposalService
from app.services.skill_workspace import SkillChange

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _proposal(**overrides: object) -> MagicMock:
    row = MagicMock(
        id=uuid.uuid4(),
        skill_id=uuid.uuid4(),
        description="How refunds work now.",
        content="Ask for the receipt.",
        resources={},
        status=ProposalStatus.PENDING.value,
    )
    row.name = "refunds"
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _change(**overrides: object) -> SkillChange:
    fields: dict[str, object] = {
        "name": "refunds",
        "skill_id": uuid.uuid4(),
        "description": "How refunds work now.",
        "content": "Ask for the receipt.",
        "resources": {},
    }
    return SkillChange(**{**fields, **overrides})  # type: ignore[arg-type]


def _service(monkeypatch) -> SkillProposalService:
    """A service whose skill writes succeed, so the tests are about the decision."""
    db = MagicMock()
    db.flush = AsyncMock()
    service = SkillProposalService(db)
    skill = MagicMock(id=uuid.uuid4())
    skill.name = "refunds"
    service.skills = MagicMock()
    service.skills.create = AsyncMock(return_value=skill)
    service.skills.update = AsyncMock(return_value=skill)
    service.skills.put_resources = AsyncMock(return_value=[])
    monkeypatch.setattr(skill_proposal_repo, "decide", AsyncMock(side_effect=_decided))
    return service


async def _decided(db, *, proposal, status, decided_by):
    proposal.status = status.value
    proposal.decided_by_user_id = decided_by
    return proposal


class TestRecordingWhatARunWrote:
    async def test_a_change_becomes_a_proposal_rather_than_an_edit(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(
            skill_proposal_repo, "get_pending_for_skill", AsyncMock(return_value=None)
        )
        created = AsyncMock(return_value=_proposal())
        monkeypatch.setattr(skill_proposal_repo, "create", created)

        recorded = await service.record(
            _ctx(), [_change()], agent_id=uuid.uuid4(), conversation_id=uuid.uuid4()
        )

        assert len(recorded) == 1
        service.skills.update.assert_not_called()
        service.skills.create.assert_not_called()

    async def test_a_second_turn_replaces_the_pending_proposal(self, monkeypatch):
        """A reviewer asked the same question three times has been given more
        work, not more information."""
        service = _service(monkeypatch)
        pending = _proposal()
        monkeypatch.setattr(
            skill_proposal_repo, "get_pending_for_skill", AsyncMock(return_value=pending)
        )
        replaced = AsyncMock(return_value=pending)
        monkeypatch.setattr(skill_proposal_repo, "replace_body", replaced)
        created = AsyncMock()
        monkeypatch.setattr(skill_proposal_repo, "create", created)

        await service.record(_ctx(), [_change()], agent_id=uuid.uuid4(), conversation_id=None)

        replaced.assert_awaited_once()
        created.assert_not_called()

    async def test_recording_nothing_writes_no_audit_entry(self, monkeypatch):
        """A run that changed nothing should be indistinguishable from one that
        has no skills, in the log as everywhere else."""
        service = _service(monkeypatch)

        assert await service.record(_ctx(), [], agent_id=uuid.uuid4(), conversation_id=None) == []


class TestApplying:
    async def test_an_edit_rewrites_the_skill_and_bumps_it(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal()
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        decided = await service.apply(_ctx(), proposal.id)

        service.skills.update.assert_awaited_once()
        assert decided.status == ProposalStatus.APPLIED.value

    async def test_a_skill_the_agent_invented_is_created_rather_than_updated(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal(skill_id=None)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        await service.apply(_ctx(), proposal.id)

        service.skills.create.assert_awaited_once()
        service.skills.update.assert_not_called()

    async def test_the_resources_are_written_too(self, monkeypatch):
        """A skill whose script did not come with it is a skill that no longer
        works, and the agent's change was to the pair."""
        service = _service(monkeypatch)
        proposal = _proposal(resources={"reconcile.py": "print(1)"})
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        await service.apply(_ctx(), proposal.id)

        files = service.skills.put_resources.await_args.args[2]
        assert files == [("reconcile.py", b"print(1)")]

    async def test_a_skill_write_that_fails_leaves_the_proposal_pending(self, monkeypatch):
        """Rather than reading "applied" beside a skill that never moved."""
        service = _service(monkeypatch)
        proposal = _proposal()
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))
        service.skills.update = AsyncMock(side_effect=RuntimeError("gone"))

        with pytest.raises(RuntimeError):
            await service.apply(_ctx(), proposal.id)

        assert proposal.status == ProposalStatus.PENDING.value

    async def test_applying_twice_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal(status=ProposalStatus.APPLIED.value)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        with pytest.raises(AlreadyExistsError) as refused:
            await service.apply(_ctx(), proposal.id)

        assert "already applied" in refused.value.message

    async def test_another_organizations_proposal_reads_as_missing(self, monkeypatch):
        """Not "forbidden": a probeable id is how a tenant boundary gets mapped."""
        service = _service(monkeypatch)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=None))

        with pytest.raises(NotFoundError):
            await service.apply(_ctx(), uuid.uuid4())


class TestDiscarding:
    async def test_the_record_survives_the_refusal(self, monkeypatch):
        """An agent proposing the same edit repeatedly is telling somebody
        something about the skill; a deleted row makes that invisible."""
        service = _service(monkeypatch)
        proposal = _proposal()
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        decided = await service.discard(_ctx(), proposal.id)

        assert decided.status == ProposalStatus.DISCARDED.value
        service.skills.update.assert_not_called()

    async def test_discarding_a_decided_proposal_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal(status=ProposalStatus.DISCARDED.value)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        with pytest.raises(AlreadyExistsError):
            await service.discard(_ctx(), proposal.id)

    async def test_discarding_one_the_agent_invented_names_no_skill(self, monkeypatch):
        """There is no skill row to attribute it to yet, and the audit entry has
        to say so rather than stringify a `None`."""
        service = _service(monkeypatch)
        proposal = _proposal(skill_id=None)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        decided = await service.discard(_ctx(), proposal.id)

        assert decided.status == ProposalStatus.DISCARDED.value


class TestListing:
    async def test_the_filter_reaches_the_repository(self, monkeypatch):
        service = _service(monkeypatch)
        listed = AsyncMock(return_value=[])
        monkeypatch.setattr(skill_proposal_repo, "list_for_organization", listed)
        ctx = _ctx()

        await service.list_proposals(ctx, status="pending")

        assert listed.await_args.kwargs == {
            "organization_id": ctx.organization_id,
            "status": "pending",
        }

    async def test_a_proposal_is_read_inside_its_organization(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal()
        got = AsyncMock(return_value=proposal)
        monkeypatch.setattr(skill_proposal_repo, "get", got)
        ctx = _ctx()

        assert await service.get(ctx, proposal.id) is proposal
        assert got.await_args.kwargs["organization_id"] == ctx.organization_id
