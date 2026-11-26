"""PostgreSQL presentation patches preserve other roles and memberships."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import deployment_settings_repo, member_repo, organization_repo
from app.schemas.console_experience import ConsoleExperienceUpdate
from app.schemas.console_presentation import ConsolePreferences
from app.services.console_experience import ConsoleExperienceService

pytestmark = pytest.mark.anyio


async def test_role_and_personal_choices_patch_and_reset_in_their_own_scope(
    db: AsyncSession,
) -> None:
    user = User(id=uuid4(), email="role-presentation@example.com", is_active=True)
    db.add(user)
    await db.flush()
    first = Organization(id=uuid4(), name="First", slug="role-first", created_by_user_id=user.id)
    other = Organization(id=uuid4(), name="Other", slug="role-other", created_by_user_id=user.id)
    db.add_all([first, other])
    await db.flush()
    db.add_all(
        [
            OrganizationMember(organization_id=org.id, user_id=user.id, role="member")
            for org in (first, other)
        ]
    )
    await db.flush()
    await organization_repo.set_console_role_defaults(
        db, first, changes={"member": {"navigation": ["chat", "inbox"]}}
    )
    await organization_repo.set_console_role_defaults(
        db, first, changes={"builder": {"navigation": ["agents"]}}
    )
    assert first.console_role_defaults == {
        "member": {"navigation": ["chat", "inbox"]},
        "builder": {"navigation": ["agents"]},
    }
    service = ConsoleExperienceService(db)
    ctx = AuthContext(user_id=user.id, organization_id=first.id, role="member")
    second = AuthContext(user_id=user.id, organization_id=other.id, role="member")
    assert (await service.read(ctx)).presentation.navigation == ["chat", "inbox"]
    await service.update(
        ctx,
        ConsoleExperienceUpdate(
            console=ConsolePreferences(navigation=["chat", "agents"], desktop_install_prompt=False)
        ),
    )
    mine = (await service.read(ctx)).presentation
    assert mine.navigation == ["chat"] and not mine.desktop_install_prompt
    assert (await service.read(second)).presentation.desktop_install_prompt
    await organization_repo.set_console_notices(db, first, changes={"product_notices": False})
    await organization_repo.set_console_notices(
        db, first, changes={"desktop_install_prompt": False}
    )
    mine = (
        await service.update(
            ctx,
            ConsoleExperienceUpdate(
                console=ConsolePreferences(product_notices=True, desktop_install_prompt=True)
            ),
        )
    ).presentation
    assert not mine.product_notices and not mine.desktop_install_prompt
    await deployment_settings_repo.upsert(
        db, update_data={"console_availability": {"navigation": ["inbox"]}}
    )
    await deployment_settings_repo.upsert(
        db, update_data={"console_availability": {"product_notices": False}}
    )
    from app.services.deployment_settings import DeploymentSettingsService

    deployment = await DeploymentSettingsService(db).read()
    assert deployment.console_availability is not None
    assert deployment.console_availability.navigation == ["inbox"]
    assert (await service.read(second)).presentation.navigation == ["inbox"]
    assert not (await service.read(second)).presentation.product_notices
    await service.update(ctx, ConsoleExperienceUpdate(console=ConsolePreferences(navigation=None)))
    assert (await service.read(ctx)).presentation.navigation == ["inbox"]
    await service.update(ctx, ConsoleExperienceUpdate(console=None))
    member = await member_repo.get_active(db, organization_id=first.id, user_id=user.id)
    assert member is not None and member.console_preferences is None
    assert (
        await member_repo.set_console_presentation(
            db, organization_id=uuid4(), user_id=user.id, changes={}
        )
        is None
    )
    await organization_repo.set_console_role_defaults(db, first, changes={"member": None})
    assert first.console_role_defaults == {"builder": {"navigation": ["agents"]}}
    await organization_repo.set_console_role_defaults(
        db, first, changes={"builder": {"navigation": None}}
    )
    assert first.console_role_defaults == {"builder": {}}
    await organization_repo.set_console_role_defaults(db, first, changes=None)
    await organization_repo.set_console_notices(db, first, changes=None)
    assert first.console_role_defaults is None and first.console_notices is None
