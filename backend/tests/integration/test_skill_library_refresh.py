"""`seed-skills` refreshing a bundled skill, against a real database.

`seed-skills` used to leave every skill an organization already had as it was, so
an improved bundled skill never reached an organization seeded with the earlier
one. It now replaces an unedited copy and leaves an edited one alone. What mocks
cannot show is the overwrite itself: the copy's files are deleted and rewritten
inside the same session that then refreshes the skill, which is the shape that
once answered a resource delete with a 500 (`remove_resource`).
"""

from __future__ import annotations

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
