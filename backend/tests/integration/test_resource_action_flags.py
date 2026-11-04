"""Action flags agree with resource grants, ownership and tenant isolation."""

from typing import Literal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.context import ContextFile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import ResourceGrant
from app.db.models.skill import Skill
from app.db.models.user import User
from app.services.context import ContextService
from app.services.organization_secret import OrganizationSecretService
from app.services.skills import SkillService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

Kind = Literal["context", "skill", "secret"]


@pytest.mark.parametrize("kind", ["context", "skill", "secret"])
@pytest.mark.parametrize("case", ["viewer-edit", "member-own", "builder-read", "foreign"])
async def test_listing_actions_follow_effective_access(
    db: AsyncSession, kind: Kind, case: str
) -> None:
    owner = User(email=f"owner-{uuid4()}@example.com", hashed_password="x")
    subject = User(email=f"subject-{uuid4()}@example.com", hashed_password="x")
    db.add_all([owner, subject])
    await db.flush()
    organization = Organization(name="Local", slug=f"local-{uuid4()}", created_by_user_id=owner.id)
    foreign = Organization(name="Foreign", slug=f"foreign-{uuid4()}", created_by_user_id=owner.id)
    db.add_all([organization, foreign])
    await db.flush()
    role = {
        "viewer-edit": "viewer",
        "member-own": "member",
        "builder-read": "builder",
        "foreign": "owner",
    }[case]
    db.add_all(
        [
            OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"),
            OrganizationMember(organization_id=organization.id, user_id=subject.id, role=role),
        ]
    )
    resource_org = foreign.id if case == "foreign" else organization.id
    resource_owner = subject.id if case == "member-own" else owner.id
    if kind == "context":
        resource = ContextFile(
            organization_id=resource_org,
            owner_user_id=resource_owner,
            visibility="private",
            name="policy",
            content="body",
            format="md",
            mode="inject",
        )
    elif kind == "skill":
        resource = Skill(
            organization_id=resource_org,
            owner_user_id=resource_owner,
            visibility="private",
            name="policy",
            content="body",
            description="Policy",
        )
    else:
        resource = OrganizationSecret(
            organization_id=resource_org,
            owner_user_id=resource_owner,
            visibility="private",
            name="key",
            kind="api_key",
            hint="abcd",
            sealed_secret="opaque-not-read",
            key_version=1,
            created_by_user_id=owner.id,
        )
    db.add(resource)
    await db.flush()
    if case in {"viewer-edit", "builder-read"}:
        db.add(
            ResourceGrant(
                organization_id=organization.id,
                resource_type=kind,
                resource_id=resource.id,
                subject_user_id=subject.id,
                level="edit" if case == "viewer-edit" else "read",
                created_by_user_id=owner.id,
            )
        )
        await db.flush()
    ctx = AuthContext(user_id=subject.id, organization_id=organization.id, role=role)
    if kind == "context":
        rows = (await ContextService(db).list_readable(ctx)).items
    elif kind == "skill":
        rows = (await SkillService(db).list_readable(ctx)).items
    else:
        rows = await OrganizationSecretService(db).list_secrets(ctx)
    if case == "foreign":
        assert rows == []
    else:
        assert len(rows) == 1 and rows[0].id == resource.id
        assert rows[0].can_edit is (case != "builder-read")
        assert "sealed_secret" not in rows[0].model_dump()
