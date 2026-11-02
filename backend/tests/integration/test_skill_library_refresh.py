"""`seed-skills` refreshing a bundled skill, against a real database.

`seed-skills` used to leave every skill an organization already had as it was, so
an improved bundled skill never reached an organization seeded with the earlier
one. It now replaces an unedited copy and leaves an edited one alone. What mocks
cannot show is the overwrite itself: the copy's files are deleted and rewritten
inside the same session that then refreshes the skill, which is the shape that
once answered a resource delete with a 500 (`remove_resource`).
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.skill import Skill
from app.db.models.user import User
from app.repositories import skill_repo
from app.schemas.skill import SkillUpdate
from app.services import skill_library
from app.services.skills import LibraryRefresh, SkillService, _fingerprint_of

pytestmark = pytest.mark.anyio

KEY = "code-review"


async def _owner_ctx(db) -> AuthContext:
    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(owner)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=owner.id,
            role=OrgRoleName.OWNER.value,
        )
    )
    await db.flush()
    return AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)


async def _copy(db, ctx: AuthContext) -> Skill:
    bundled = skill_library.get(KEY)
    assert bundled is not None
    row = await skill_repo.get_by_name(db, bundled.name, organization_id=ctx.organization_id)
    assert row is not None
    await db.refresh(row, ["resources"])
    return row


async def _as_an_earlier_release(db, ctx: AuthContext) -> Skill:
    """Install the skill, then make the copy look seeded from an older folder.

    An older bundled version is what the copy said when it was seeded and what
    its fingerprint was stamped from - so both change together, and the copy is
    still unedited by anybody here.
    """
    await SkillService(db).install_from_library(ctx, KEY)
    row = await _copy(db, ctx)
    first = row.resources[0]
    await skill_repo.update_resource(db, resource=first, update_data={"content": "old file"})
    extra = await skill_repo.create_resource(
        db, skill_id=row.id, name="retired.md", description=None, content="gone next release"
    )
    assert extra is not None
    await db.refresh(row, ["resources"])
    row = await skill_repo.update(db, skill=row, update_data={"content": "The old body."})
    await db.refresh(row, ["resources"])
    return await skill_repo.update(
        db, skill=row, update_data={"library_fingerprint": _fingerprint_of(row)}
    )


async def test_a_fresh_install_is_stamped_and_then_current(db) -> None:
    ctx = await _owner_ctx(db)
    service = SkillService(db)

    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.INSTALL
    row = await _copy(db, ctx)
    bundled = skill_library.get(KEY)
    assert bundled is not None
    assert row.library_fingerprint == bundled.fingerprint

    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.CURRENT


async def test_an_unedited_copy_of_an_earlier_release_is_brought_up_to_date(db) -> None:
    ctx = await _owner_ctx(db)
    before = await _as_an_earlier_release(db, ctx)
    version = before.version

    assert await SkillService(db).refresh_from_library(ctx, KEY) is LibraryRefresh.UPDATE

    row = await _copy(db, ctx)
    bundled = skill_library.get(KEY)
    assert bundled is not None
    assert row.content == bundled.content
    assert sorted((r.name, r.content) for r in row.resources) == sorted(
        (r.name, r.content) for r in bundled.resources
    )
    assert row.version == version + 1
    assert row.library_fingerprint == bundled.fingerprint
    entry = (
        await db.execute(
            select(AppAdminAuditLog).where(
                AppAdminAuditLog.organization_id == ctx.organization_id,
                AppAdminAuditLog.action == "skill.refreshed",
            )
        )
    ).scalar_one()
    assert entry.details["replaced_edits"] is False


async def test_a_copy_edited_here_is_left_alone(db) -> None:
    ctx = await _owner_ctx(db)
    service = SkillService(db)
    await service.install_from_library(ctx, KEY)
    row = await _copy(db, ctx)
    await service.update(ctx, row.id, SkillUpdate(content="Our own review rules."))

    assert await service.plan_library_refresh(ctx, KEY) is LibraryRefresh.EDITED
    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.EDITED
    assert (await _copy(db, ctx)).content == "Our own review rules."


async def test_replace_takes_the_bundled_version_over_edits_and_says_so(db) -> None:
    ctx = await _owner_ctx(db)
    service = SkillService(db)
    await service.install_from_library(ctx, KEY)
    row = await _copy(db, ctx)
    await service.update(ctx, row.id, SkillUpdate(content="Our own review rules."))

    assert (
        await service.refresh_from_library(ctx, KEY, replace_edited=True) is LibraryRefresh.UPDATE
    )

    bundled = skill_library.get(KEY)
    assert bundled is not None
    assert (await _copy(db, ctx)).content == bundled.content
    entry = (
        await db.execute(
            select(AppAdminAuditLog).where(
                AppAdminAuditLog.organization_id == ctx.organization_id,
                AppAdminAuditLog.action == "skill.refreshed",
            )
        )
    ).scalar_one()
    assert entry.details["replaced_edits"] is True


async def test_a_copy_from_before_fingerprints_is_untracked_unless_it_matches(db) -> None:
    """Nothing can tell whether such a copy was edited, so a different one is left
    alone; one that already says what the folder says is simply stamped."""
    ctx = await _owner_ctx(db)
    service = SkillService(db)
    await service.install_from_library(ctx, KEY)
    row = await _copy(db, ctx)
    await skill_repo.update(db, skill=row, update_data={"library_fingerprint": None})

    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.CURRENT
    bundled = skill_library.get(KEY)
    assert bundled is not None
    assert (await _copy(db, ctx)).library_fingerprint == bundled.fingerprint

    row = await _copy(db, ctx)
    await skill_repo.update(
        db, skill=row, update_data={"library_fingerprint": None, "content": "Older body."}
    )
    assert await service.plan_library_refresh(ctx, KEY) is LibraryRefresh.UNTRACKED
    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.UNTRACKED
    assert (await _copy(db, ctx)).content == "Older body."


async def test_a_file_description_written_here_counts_as_an_edit(db) -> None:
    """The shipped files carry no description, so one written on the copy is the
    organization's - replacing the file would drop it without `--replace`."""
    ctx = await _owner_ctx(db)
    await _as_an_earlier_release(db, ctx)
    row = await _copy(db, ctx)
    await skill_repo.update_resource(
        db, resource=row.resources[0], update_data={"description": "Our note on this file"}
    )

    assert await SkillService(db).refresh_from_library(ctx, KEY) is LibraryRefresh.EDITED
    row = await _copy(db, ctx)
    assert "Our note on this file" in [resource.description for resource in row.resources]


async def test_the_decision_is_made_on_the_row_as_it_is_now(db, monkeypatch) -> None:
    """A copy edited after the lookup must not be judged on the copy as it was."""
    ctx = await _owner_ctx(db)
    await _as_an_earlier_release(db, ctx)
    service = SkillService(db)
    looked_up = service._library_pair

    async def lookup_then_somebody_edits(context: AuthContext, key: str):
        bundled, existing = await looked_up(context, key)
        assert existing is not None
        # A member's edit, committed through its own statement between the lookup
        # and the overwrite; the loaded object still says the old thing.
        await db.execute(
            Skill.__table__.update()
            .where(Skill.id == existing.id)
            .values(content="Edited just now.")
        )
        return bundled, existing

    monkeypatch.setattr(service, "_library_pair", lookup_then_somebody_edits)

    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.EDITED
    assert (await _copy(db, ctx)).content == "Edited just now."


async def test_gallery_refresh_can_inspect_install_and_adopt_a_copy(db) -> None:
    ctx = await _owner_ctx(db)
    service = SkillService(db)
    key = "software/agenticos-guide"
    bundled = skill_library.gallery_get(key)
    assert bundled is not None
    assert await service.refresh_gallery(ctx, key, dry_run=True) is LibraryRefresh.INSTALL
    assert (
        await skill_repo.get_by_name(db, bundled.name, organization_id=ctx.organization_id) is None
    )
    assert await service.refresh_gallery(ctx, key) is LibraryRefresh.INSTALL
    copy = await skill_repo.get_by_name(db, bundled.name, organization_id=ctx.organization_id)
    assert copy is not None and copy.library_fingerprint == bundled.fingerprint
    assert await service.refresh_gallery(ctx, key, dry_run=True) is LibraryRefresh.CURRENT


async def test_an_update_agents_follow_waits_as_a_proposal_until_it_is_checked(
    db, monkeypatch
) -> None:
    """A release's better text still changes what every following agent does; it goes
    live through a check on them, like any other change to a shared skill."""
    from typing import cast

    from app.db.models.agent import Agent
    from app.repositories import skill_proposal_repo
    from app.services.skill_agents import LineAgent, SkillAgentService

    ctx = await _owner_ctx(db)
    before = await _as_an_earlier_release(db, ctx)

    async def followers(_self, skill, fork_id):
        return [LineAgent(agent=cast(Agent, object()), agent_version=1, via_specialist=None)]

    monkeypatch.setattr(SkillAgentService, "line_agents", followers)
    service = SkillService(db)

    assert await service.plan_library_refresh(ctx, KEY) is LibraryRefresh.WAITING
    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.WAITING
    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.WAITING

    after = await _copy(db, ctx)
    assert (after.version, after.content) == (before.version, "The old body.")
    waiting = await skill_proposal_repo.from_source(
        db, organization_id=ctx.organization_id, skill_id=after.id, source="library"
    )
    bundled = skill_library.get(KEY)
    assert bundled is not None
    assert [item.content for item in waiting] == [bundled.content]
    assert waiting[0].base_version_id == after.latest_version_id


async def test_a_newer_release_withdraws_the_older_waiting_one_and_a_decided_one_stays_decided(
    db, monkeypatch
) -> None:
    from typing import cast

    from app.db.models.agent import Agent
    from app.db.models.skill_proposal import ProposalStatus
    from app.repositories import skill_proposal_repo
    from app.services.skill_agents import LineAgent, SkillAgentService

    ctx = await _owner_ctx(db)
    copy = await _as_an_earlier_release(db, ctx)
    copy = await skill_repo.update(db, skill=copy, update_data={"category": "old-shelf"})
    copy = await skill_repo.update(
        db, skill=copy, update_data={"library_fingerprint": _fingerprint_of(copy)}
    )

    async def followers(_self, skill, fork_id):
        return [LineAgent(agent=cast(Agent, object()), agent_version=1, via_specialist=None)]

    monkeypatch.setattr(SkillAgentService, "line_agents", followers)
    older = await skill_proposal_repo.create(
        db,
        organization_id=ctx.organization_id,
        skill_id=copy.id,
        agent_id=None,
        conversation_id=None,
        name=copy.name,
        description=copy.description,
        content="What an earlier release said.",
        resources={},
        base_version=copy.version,
        base_version_id=copy.latest_version_id,
        fork_id=None,
    )
    await skill_proposal_repo.annotate(db, proposal=older, values={"source": "library"})
    long_ago = await skill_proposal_repo.create(
        db,
        organization_id=ctx.organization_id,
        skill_id=copy.id,
        agent_id=None,
        conversation_id=None,
        name=copy.name,
        description=copy.description,
        content="What a release long ago said.",
        resources={},
        base_version=copy.version,
        base_version_id=copy.latest_version_id,
        fork_id=None,
    )
    await skill_proposal_repo.annotate(
        db, proposal=long_ago, values={"source": "library", "status": "discarded"}
    )
    service = SkillService(db)

    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.WAITING

    await db.refresh(older)
    assert older.status == ProposalStatus.DISCARDED.value
    bundled = skill_library.get(KEY)
    assert bundled is not None
    assert (await _copy(db, ctx)).category == bundled.category
    every = await skill_proposal_repo.from_source(
        db, organization_id=ctx.organization_id, skill_id=copy.id, source="library"
    )
    newest = next(item for item in every if item.status == ProposalStatus.PENDING.value)
    await skill_proposal_repo.decide_if(
        db,
        proposal_id=newest.id,
        organization_id=ctx.organization_id,
        revision=newest.revision,
        status=ProposalStatus.DISCARDED,
        decided_by=ctx.user_id,
    )

    await skill_repo.update(db, skill=await _copy(db, ctx), update_data={"category": "moved"})
    stamped = await _copy(db, ctx)
    await skill_repo.update(
        db, skill=stamped, update_data={"library_fingerprint": _fingerprint_of(stamped)}
    )
    assert await service.refresh_from_library(ctx, KEY) is LibraryRefresh.WAITING
    assert (await _copy(db, ctx)).category == bundled.category
    again = await skill_proposal_repo.from_source(
        db, organization_id=ctx.organization_id, skill_id=copy.id, source="library"
    )
    assert [item.status for item in again if item.status == ProposalStatus.PENDING.value] == []


async def test_a_copy_edited_here_and_replaced_on_request_keeps_its_own_stamp(
    db, monkeypatch
) -> None:
    """`--replace` takes the bundled version over edits; until it is applied the copy
    is still the organization's edit, and moving its category does not hide that."""
    from typing import cast

    from app.db.models.agent import Agent
    from app.services.skill_agents import LineAgent, SkillAgentService

    ctx = await _owner_ctx(db)
    copy = await _as_an_earlier_release(db, ctx)
    stamp = copy.library_fingerprint
    copy = await skill_repo.update(
        db, skill=copy, update_data={"content": "Edited here.", "category": "old-shelf"}
    )

    async def followers(_self, skill, fork_id):
        return [LineAgent(agent=cast(Agent, object()), agent_version=1, via_specialist=None)]

    monkeypatch.setattr(SkillAgentService, "line_agents", followers)

    plan = await SkillService(db).refresh_from_library(ctx, KEY, replace_edited=True)

    assert plan is LibraryRefresh.WAITING
    assert (await _copy(db, ctx)).library_fingerprint == stamp


async def test_withdrawing_a_waiting_update_stops_its_check(db, monkeypatch) -> None:
    """A newer release withdraws the older waiting update; checking it further would
    spend the agents' budget on a change nobody can apply any more."""
    from typing import cast

    from app.db.models.agent import Agent
    from app.repositories import skill_proposal_repo
    from app.services.skill_agents import LineAgent, SkillAgentService
    from app.services.skill_check import SkillCheckService

    ctx = await _owner_ctx(db)
    copy = await _as_an_earlier_release(db, ctx)

    async def followers(_self, skill, fork_id):
        return [LineAgent(agent=cast(Agent, object()), agent_version=1, via_specialist=None)]

    monkeypatch.setattr(SkillAgentService, "line_agents", followers)
    older = await skill_proposal_repo.create(
        db,
        organization_id=ctx.organization_id,
        skill_id=copy.id,
        agent_id=None,
        conversation_id=None,
        name=copy.name,
        description=copy.description,
        content="What an earlier release said.",
        resources={},
        base_version=copy.version,
        base_version_id=copy.latest_version_id,
        fork_id=None,
    )
    await skill_proposal_repo.annotate(db, proposal=older, values={"source": "library"})
    stopped: list[object] = []

    async def stop(_self, _ctx, skill_id, proposal_id):
        stopped.append(proposal_id)

    monkeypatch.setattr(SkillCheckService, "stop_for_proposal", stop)

    await SkillService(db).refresh_from_library(ctx, KEY)

    assert stopped == [older.id]
