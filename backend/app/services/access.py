"""Resource-level access resolution - where role scopes and grants combine.

A role says how much of a resource *type* a member reaches (:class:`Scope`); a
grant says what they may do with one specific row. Effective access is the
better of the two, never the worse:

    effective = max(role scope, grant on this resource)

so sharing a single agent with a Viewer works without promoting them, and a
Builder's org-wide view is not taken away by the absence of a grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, OrgRoleName, Perm, Scope
from app.db.models.resource_grant import GRANT_ORDER, GrantLevel, Visibility
from app.repositories import member_repo, resource_grant_repo


class OwnedResource(Protocol):
    """The shape every shareable resource has: an owner and a visibility.

    `organization_id` is optional because one of the tables that satisfies this
    protocol has it nullable - `knowledge_bases`, inherited from the generator.
    Nothing here treats `None` as a wildcard: `resolve_access` compares it to the
    caller's organization, and a row with no organization matches no caller and
    is refused. Declaring it non-optional would only mean the one resource type
    that needs checking most could not be passed in.
    """

    id: UUID
    owner_user_id: UUID | None
    visibility: str

    # Read-only, so a model declaring it non-nullable still satisfies this. A
    # mutable protocol attribute is invariant, and nothing here assigns a
    # resource's organization - it is what a resource is filed under, not
    # something sharing changes.
    @property
    def organization_id(self) -> UUID | None: ...


@dataclass(frozen=True)
class ResourceType:
    """A resource kind and the permissions that govern it.

    Agents and skills join collections here once their tables exist (sections
    E-G); the resolution rules below are already type-agnostic.
    """

    key: str
    view: Perm
    edit: Perm


COLLECTION = ResourceType(key="collection", view=Perm.COLLECTIONS_VIEW, edit=Perm.COLLECTIONS_EDIT)
AGENT = ResourceType(key="agent", view=Perm.AGENTS_VIEW, edit=Perm.AGENTS_EDIT)
SKILL = ResourceType(key="skill", view=Perm.SKILLS_VIEW, edit=Perm.SKILLS_EDIT)
# A stored key. The same rules as everything else here on purpose: a personal
# key is private to its owner, a team key reaches whoever holds a grant, and an
# organization key is everybody's - decided per row rather than by one
# permission that gated the entire vault.
SECRET = ResourceType(key="secret", view=Perm.SECRETS_VIEW, edit=Perm.SECRETS_EDIT)


# The grant level a member needs before a scope-based check is even consulted.
_PERM_MIN_GRANT: dict[Perm, GrantLevel] = {
    Perm.AGENTS_VIEW: GrantLevel.READ,
    Perm.AGENTS_RUN: GrantLevel.USE,
    Perm.AGENTS_EDIT: GrantLevel.EDIT,
    Perm.AGENTS_PUBLISH: GrantLevel.EDIT,
    Perm.COLLECTIONS_VIEW: GrantLevel.READ,
    Perm.COLLECTIONS_EDIT: GrantLevel.EDIT,
    Perm.SKILLS_VIEW: GrantLevel.READ,
    Perm.SKILLS_EDIT: GrantLevel.EDIT,
    Perm.SECRETS_VIEW: GrantLevel.READ,
    Perm.SECRETS_EDIT: GrantLevel.EDIT,
}


def _scope_allows(scope: Scope, resource: OwnedResource, user_id: UUID) -> bool:
    """Whether a role scope alone reaches this row."""
    if scope is Scope.ALL:
        return True
    is_owner = resource.owner_user_id is not None and resource.owner_user_id == user_id
    if scope is Scope.TEAM:
        return is_owner or resource.visibility in (Visibility.TEAM, Visibility.ORG)
    if scope is Scope.SHARED:
        # "Mine plus what was shared with me" - org-wide visibility counts as
        # shared with everyone; an explicit grant is checked separately.
        return is_owner or resource.visibility == Visibility.ORG
    if scope is Scope.OWN:
        return is_owner
    return False


async def resolve_access(
    db: AsyncSession,
    ctx: AuthContext,
    resource: OwnedResource,
    perm: Perm,
    *,
    resource_type: ResourceType,
) -> bool:
    """Whether `ctx` may exercise `perm` on this specific resource.

    Checks the role scope first (no query in the common case), then falls back
    to an explicit grant. A grant can lift access the role does not give -
    that is the point of sharing - but it never applies across organizations:
    a resource from another tenant is refused before either check runs.

    A context with no subject reaches nothing at all, and is refused before the
    grant table is consulted. Both halves matter. Scopes and grants are answers
    to "what may *this person* do", and there is no person here - an anonymous
    visitor's access comes from the exposure that admitted them, not from this
    function. And a lookup keyed on a `NULL` subject asks the database a
    question whose answer depends on what rows happen to exist rather than on
    the invariant, so it is never asked.
    """
    subject = ctx.user_id
    if subject is None:
        return False

    if resource.organization_id != ctx.organization_id:
        return False

    if _scope_allows(ctx.scope_for(perm), resource, subject):
        return True

    required = _PERM_MIN_GRANT.get(perm)
    if required is None:
        return False

    granted = await resource_grant_repo.get_level(
        db,
        organization_id=ctx.organization_id,
        subject_user_id=subject,
        resource_type=resource_type.key,
        resource_id=resource.id,
    )
    if granted is None:
        return False
    return GRANT_ORDER[granted] >= GRANT_ORDER[required]


async def visible_resource_ids(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    resource_type: ResourceType,
    perm: Perm,
) -> list[UUID] | None:
    """Extra resource ids a listing must include beyond the scope predicate.

    Returns `None` when the role already reaches everything, so the caller can
    skip the grant lookup entirely.

    A context with no subject gets the empty list, never `None`. The two are
    opposites here - every caller reads `None` as "no filtering needed" - so
    returning it for an anonymous visitor would widen a listing to the whole
    organization at the exact moment it should be narrowed to nothing.
    """
    subject = ctx.user_id
    if subject is None:
        return []
    if ctx.scope_for(perm) is Scope.ALL:
        return None
    required = _PERM_MIN_GRANT.get(perm, GrantLevel.READ)
    return await resource_grant_repo.list_shared_ids(
        db,
        organization_id=ctx.organization_id,
        subject_user_id=subject,
        resource_type=resource_type.key,
        minimum_level=required,
    )


async def publisher_context(
    db: AsyncSession,
    *,
    organization_id: UUID,
    publisher_user_id: UUID | None,
    channel_identity_id: UUID | None = None,
) -> AuthContext:
    """The role a turn nobody can name runs under: whoever published the surface.

    A widget on somebody's site, a hosted page behind a link, an agent bound to a
    Slack channel - on all three the person in front of it is anonymous or is a chat
    account with no platform user behind it, and a run still takes a subject: the
    role is what resolves what the agent may reach. So it is the member who
    published, which is both the honest record and the only answer available.

    **`viewer` when they are no longer a member, and when there is no publisher
    recorded at all.** Their departure must not silently *widen* what a public
    surface reaches, and neither must a row old enough to predate the column naming
    who made it. That is the whole reason this function exists rather than the two
    call sites reading a membership each: it was written twice - once for
    `agent_embeds.owner_user_id` and once for `agent_exposures.created_by_user_id` -
    and two copies of an authorization decision is one that gets fixed once (#640).

    `channel_identity_id` is a *different* fact and is only passed through: it
    records who **asked**, while the role comes from who **published**. Merging them
    would make a channel run claim the sender's authority, which is exactly what an
    unlinked sender does not have.
    """
    role = OrgRoleName.VIEWER.value
    if publisher_user_id is not None:
        membership = await member_repo.get(
            db, organization_id=organization_id, user_id=publisher_user_id
        )
        if membership is not None:
            role = membership.role
    return AuthContext(
        user_id=publisher_user_id,
        organization_id=organization_id,
        role=role,
        channel_identity_id=channel_identity_id,
    )
