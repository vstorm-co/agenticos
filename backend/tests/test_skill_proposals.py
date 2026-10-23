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

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AlreadyExistsError, ConcurrentChangeError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.skill_proposal import ProposalStatus, SkillProposal
from app.repositories import skill_proposal_repo, skill_repo
from app.schemas.resource_usage import ProposalDecision
from app.services import proposal_reach
from app.services.skill_proposal import SkillProposalService
from app.services.skill_workspace import SkillChange

pytestmark = pytest.mark.anyio

_DECISION = ProposalDecision(revision=1)
_ROWS: dict[uuid.UUID, MagicMock] = {}


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
        base_version=None,
        revision=1,
    )
    row.name = "refunds"
    for key, value in overrides.items():
        setattr(row, key, value)
    _ROWS[row.id] = row
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
    # `record_audit` reads the chain head and takes the per-org lock, both via
    # `execute`; the mock must await and answer the head read with an empty chain.
    db.execute = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    service = SkillProposalService(db)
    skill = MagicMock(id=uuid.uuid4())
    skill.name = "refunds"
    service.skills = MagicMock()
    service.skills.create = AsyncMock(return_value=skill)
    service.skills.update = AsyncMock(return_value=skill)
    service.skills.put_resources = AsyncMock(return_value=[])
    monkeypatch.setattr(skill_proposal_repo, "decide_if", AsyncMock(side_effect=_decided))
    monkeypatch.setattr(
        proposal_reach,
        "reach",
        AsyncMock(
            side_effect=lambda *_, resource_ids, **__: {
                resource_id: [] for resource_id in resource_ids
            }
        ),
    )
    return service


async def _decided(db, *, proposal_id, organization_id, revision, status, decided_by):
    """The conditional update, as Postgres answers it for one session."""
    proposal = _ROWS[proposal_id]
    if proposal.status != ProposalStatus.PENDING.value or proposal.revision != revision:
        return None
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

        decided = await service.apply(_ctx(), proposal.id, _DECISION)

        service.skills.update.assert_awaited_once()
        assert decided.status == ProposalStatus.APPLIED.value

    async def test_a_skill_the_agent_invented_is_created_rather_than_updated(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal(skill_id=None)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        await service.apply(_ctx(), proposal.id, _DECISION)

        service.skills.create.assert_awaited_once()
        service.skills.update.assert_not_called()

    async def test_a_proposal_applies_while_the_skill_is_at_its_version(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal(base_version=3)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))
        service.skills.get = AsyncMock(return_value=MagicMock(version=3))
        monkeypatch.setattr(skill_repo, "lock", AsyncMock())

        decided = await service.apply(_ctx(), proposal.id, _DECISION)

        assert decided.status == ProposalStatus.APPLIED.value

    async def test_a_proposal_for_an_older_version_refuses_to_overwrite(self, monkeypatch):
        """A body reviewed against v3 must not silently replace the v4 somebody wrote."""
        service = _service(monkeypatch)
        proposal = _proposal(base_version=3)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))
        service.skills.get = AsyncMock(return_value=MagicMock(version=4))
        monkeypatch.setattr(skill_repo, "lock", AsyncMock())

        with pytest.raises(ConcurrentChangeError, match="changed since"):
            await service.apply(_ctx(), proposal.id, _DECISION)

        service.skills.update.assert_not_called()
        assert proposal.status == ProposalStatus.PENDING.value

    async def test_an_edit_committed_while_waiting_for_the_lock_is_seen(self, monkeypatch):
        """The version is compared after the lock re-reads the row, not before."""
        service = _service(monkeypatch)
        proposal = _proposal(base_version=3)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))
        skill = MagicMock(version=3)
        service.skills.get = AsyncMock(return_value=skill)

        async def edited_meanwhile(_db: object, _skill_id: object) -> MagicMock:
            skill.version = 4
            return skill

        monkeypatch.setattr(skill_repo, "lock", edited_meanwhile)

        with pytest.raises(ConcurrentChangeError, match="now v4"):
            await service.apply(_ctx(), proposal.id, _DECISION)

        service.skills.update.assert_not_called()

    async def test_the_resources_are_written_too(self, monkeypatch):
        """A skill whose script did not come with it is a skill that no longer
        works, and the agent's change was to the pair."""
        service = _service(monkeypatch)
        proposal = _proposal(resources={"reconcile.py": "print(1)"})
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        await service.apply(_ctx(), proposal.id, _DECISION)

        files = service.skills.put_resources.await_args.args[2]
        assert files == [("reconcile.py", b"print(1)")]

    async def test_a_skill_write_that_fails_fails_the_decision_with_it(self, monkeypatch):
        """The decision and the write are one transaction: a write that fails
        raises through, and rolling it back leaves the proposal pending rather
        than "applied" beside a skill that never moved."""
        service = _service(monkeypatch)
        proposal = _proposal()
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))
        service.skills.update = AsyncMock(side_effect=RuntimeError("gone"))

        with pytest.raises(RuntimeError):
            await service.apply(_ctx(), proposal.id, _DECISION)

    async def test_applying_twice_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal(status=ProposalStatus.APPLIED.value)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        with pytest.raises(AlreadyExistsError) as refused:
            await service.apply(_ctx(), proposal.id, _DECISION)

        assert "already applied" in refused.value.message

    async def test_another_organizations_proposal_reads_as_missing(self, monkeypatch):
        """Not "forbidden": a probeable id is how a tenant boundary gets mapped."""
        service = _service(monkeypatch)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=None))

        with pytest.raises(NotFoundError):
            await service.apply(_ctx(), uuid.uuid4(), _DECISION)


class TestDiscarding:
    async def test_the_record_survives_the_refusal(self, monkeypatch):
        """An agent proposing the same edit repeatedly is telling somebody
        something about the skill; a deleted row makes that invisible."""
        service = _service(monkeypatch)
        proposal = _proposal()
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        decided = await service.discard(_ctx(), proposal.id, _DECISION)

        assert decided.status == ProposalStatus.DISCARDED.value
        service.skills.update.assert_not_called()

    async def test_discarding_a_decided_proposal_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal(status=ProposalStatus.DISCARDED.value)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        with pytest.raises(AlreadyExistsError):
            await service.discard(_ctx(), proposal.id, _DECISION)

    async def test_discarding_one_the_agent_invented_names_no_skill(self, monkeypatch):
        """There is no skill row to attribute it to yet, and the audit entry has
        to say so rather than stringify a `None`."""
        service = _service(monkeypatch)
        proposal = _proposal(skill_id=None)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        decided = await service.discard(_ctx(), proposal.id, _DECISION)

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


class TestReading:
    def _proposal(self) -> SkillProposal:
        return SkillProposal(
            id=uuid.uuid4(),
            name="refunds",
            description="d",
            content="c",
            resources={},
            status="pending",
            revision=1,
            evidence=[{"run_id": "run-1", "quote": "Thirty days"}],
            evidence_dropped=0,
            rationale="",
            expected_effect="",
            created_at=datetime.now(UTC),
        )

    @pytest.mark.security
    async def test_a_reviewer_without_runs_view_gets_the_runs_but_not_the_words(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = self._proposal()
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))
        monkeypatch.setattr(
            skill_proposal_repo, "list_for_organization", AsyncMock(return_value=[proposal])
        )
        member = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER.value
        )

        hidden = await service.read(member, proposal.id)
        shown = await service.list_read(_ctx())

        assert hidden.evidence == [{"run_id": "run-1", "quote": None}]
        assert shown[0].evidence == [{"run_id": "run-1", "quote": "Thirty days"}]


class TestRevision:
    """A decision names the revision the reviewer read; a newer run, or a decision
    made first, leaves nothing for it to decide."""

    async def test_a_decision_on_an_older_revision_is_refused_before_anything_is_written(
        self, monkeypatch
    ):
        service = _service(monkeypatch)
        proposal = _proposal(revision=3)
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))

        for decide in (service.apply, service.discard):
            with pytest.raises(ConcurrentChangeError, match="changed since you opened it"):
                await decide(_ctx(), proposal.id, ProposalDecision(revision=2))

        service.skills.update.assert_not_called()
        assert proposal.status == ProposalStatus.PENDING.value

    async def test_the_decision_that_loses_the_race_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        proposal = _proposal()
        monkeypatch.setattr(skill_proposal_repo, "get", AsyncMock(return_value=proposal))
        monkeypatch.setattr(skill_proposal_repo, "decide_if", AsyncMock(return_value=None))

        for decide in (service.apply, service.discard):
            with pytest.raises(ConcurrentChangeError, match="Review the new version"):
                await decide(_ctx(), proposal.id, _DECISION)

        service.skills.update.assert_not_called()
