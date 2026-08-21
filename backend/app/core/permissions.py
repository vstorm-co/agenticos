"""Permission catalog - the single source of truth for what a member may do.

The rule the rest of the codebase follows: **permissions are defined in code,
roles are composed from them.** Call sites check permissions, never role names,
so adding or re-shaping a role never means editing an endpoint.

Two kinds of permission, and they behave differently:

*Global* permissions are binary and org-wide - you may manage members, or you
may not. *Resource* permissions carry a :class:`Scope` answering the second
question a role cannot: not "may this role touch agents?" but "*which* agents?"
A Member creates their own agents and sees only those plus what was shared with
them; a Builder sees every agent in the org but may only edit the shared ones.

Effective access to one resource is `max(role scope, grant on that resource)`
- see :func:`app.services.access.resolve_access`. A grant can widen what a role
allows for a single row; it never narrows it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.core.exceptions import AuthorizationError


class Perm(StrEnum):
    """Everything a member can be allowed to do.

    Clients cannot invent permissions - a custom role (Phase 2) may only
    recombine the values listed here.
    """

    AGENTS_VIEW = "agents:view"
    AGENTS_EDIT = "agents:edit"
    AGENTS_PUBLISH = "agents:publish"
    AGENTS_RUN = "agents:run"
    COLLECTIONS_VIEW = "collections:view"
    COLLECTIONS_EDIT = "collections:edit"
    SKILLS_VIEW = "skills:view"
    SKILLS_EDIT = "skills:edit"
    # Context files are a shared resource shaped exactly like skills: an owner, a
    # visibility, grants. Their own permission rather than reusing `skills:*`
    # because a role may reasonably reach one and not the other.
    CONTEXT_VIEW = "context:view"
    CONTEXT_EDIT = "context:edit"
    # A stored key is a shared resource like any other: it has an owner, a
    # visibility and grants. `connections:manage` used to gate the whole vault,
    # which made "can see every key in the organization" and "can add a bot"
    # the same answer - and left a member no way to keep a key of their own.
    SECRETS_VIEW = "secrets:view"
    SECRETS_EDIT = "secrets:edit"

    APPROVALS_DECIDE = "approvals:decide"
    # Watching a host and managing one are separate authorities. Reading a
    # connection's session list, its activity log and the ceilings its service
    # enforces answers "why did that agent get a 429", which is the question an
    # operator is paged about; pointing a connection at an address and attaching
    # a vault secret to it decides which host an agent's shell runs on. One
    # permission for both meant the second had to be granted to permit the first.
    CONNECTIONS_VIEW = "connections:view"
    CONNECTIONS_MANAGE = "connections:manage"
    MCP_MANAGE = "mcp:manage"
    CHANNELS_MANAGE = "channels:manage"
    MEMBERS_MANAGE = "members:manage"
    ROLES_MANAGE = "roles:manage"
    ORG_SETTINGS = "org:settings"
    ORG_DELETE = "org:delete"
    BUDGETS_MANAGE = "budgets:manage"
    RUNS_VIEW = "runs:view"
    AUDIT_READ = "audit:read"


RESOURCE_PERMS: frozenset[Perm] = frozenset(
    {
        Perm.AGENTS_VIEW,
        Perm.AGENTS_EDIT,
        Perm.AGENTS_PUBLISH,
        Perm.AGENTS_RUN,
        Perm.COLLECTIONS_VIEW,
        Perm.COLLECTIONS_EDIT,
        Perm.SKILLS_VIEW,
        Perm.SKILLS_EDIT,
        Perm.CONTEXT_VIEW,
        Perm.CONTEXT_EDIT,
        Perm.SECRETS_VIEW,
        Perm.SECRETS_EDIT,
    }
)


class Scope(StrEnum):
    """How much of a resource type a permission reaches.

    Ordered: `NONE < OWN < SHARED < TEAM < ALL`. Comparison is what makes
    "effective access = max(role, grant)" expressible, so use the operators
    rather than comparing the string values.
    """

    NONE = "none"
    OWN = "own"
    SHARED = "shared"
    TEAM = "team"
    ALL = "all"

    @property
    def rank(self) -> int:
        return _SCOPE_ORDER[self]

    @staticmethod
    def _other_rank(other: object) -> int:
        """Rank of the operand, refusing anything that is not a Scope.

        Returning `NotImplemented` would be the usual convention, but `Scope`
        subclasses `str`: Python would fall back to string comparison, which
        orders the values alphabetically (`all < none < own`) - the opposite of
        what they mean. A silent wrong answer in an authorization check is worse
        than a loud one, so mixed comparisons raise.
        """
        if not isinstance(other, Scope):
            raise TypeError(f"Scope can only be compared to Scope, not {type(other).__name__}")
        return other.rank

    def __lt__(self, other: object) -> bool:
        return self.rank < self._other_rank(other)

    def __le__(self, other: object) -> bool:
        return self.rank <= self._other_rank(other)

    def __gt__(self, other: object) -> bool:
        return self.rank > self._other_rank(other)

    def __ge__(self, other: object) -> bool:
        return self.rank >= self._other_rank(other)


_SCOPE_ORDER: dict[Scope, int] = {
    Scope.NONE: 0,
    Scope.OWN: 1,
    Scope.SHARED: 2,
    Scope.TEAM: 3,
    Scope.ALL: 4,
}


class OrgRoleName(StrEnum):
    """The role names a membership row may hold.

    Nothing seeds these and there is no roles table: a role is a string on
    `organization_members`, and what it *means* is `ROLE_PERMS` below. Adding a
    role is an edit here, not a migration - which is the point of composing
    roles from permissions rather than storing them.

    The column carries no CHECK constraint, unlike `resource_grants.level`.
    What keeps an invented role out is a `field_validator` on the member and
    invitation schemas; if one ever got through, `ROLE_PERMS.get` would answer
    with no permissions rather than with somebody else's.

    Not user-editable. Custom roles are Phase 2, and may only ever recombine
    the permissions in :class:`Perm`.
    """

    OWNER = "owner"
    ADMIN = "admin"
    BUILDER = "builder"
    OPERATOR = "operator"
    MEMBER = "member"
    VIEWER = "viewer"


_ALL_GLOBAL: dict[Perm, Scope] = {perm: Scope.ALL for perm in Perm if perm not in RESOURCE_PERMS}

ROLE_PERMS: dict[str, dict[Perm, Scope]] = {
    OrgRoleName.OWNER: {
        **_ALL_GLOBAL,
        Perm.SECRETS_VIEW: Scope.ALL,
        Perm.SECRETS_EDIT: Scope.ALL,
        Perm.AGENTS_VIEW: Scope.ALL,
        Perm.AGENTS_EDIT: Scope.ALL,
        Perm.AGENTS_PUBLISH: Scope.ALL,
        Perm.AGENTS_RUN: Scope.ALL,
        Perm.COLLECTIONS_VIEW: Scope.ALL,
        Perm.COLLECTIONS_EDIT: Scope.ALL,
        Perm.SKILLS_VIEW: Scope.ALL,
        Perm.SKILLS_EDIT: Scope.ALL,
        Perm.CONTEXT_VIEW: Scope.ALL,
        Perm.CONTEXT_EDIT: Scope.ALL,
    },
    # Admin runs the org day to day but cannot delete it.
    OrgRoleName.ADMIN: {
        **{perm: Scope.ALL for perm in _ALL_GLOBAL if perm is not Perm.ORG_DELETE},
        Perm.SECRETS_VIEW: Scope.ALL,
        Perm.SECRETS_EDIT: Scope.ALL,
        Perm.AGENTS_VIEW: Scope.ALL,
        Perm.AGENTS_EDIT: Scope.ALL,
        Perm.AGENTS_PUBLISH: Scope.ALL,
        Perm.AGENTS_RUN: Scope.ALL,
        Perm.COLLECTIONS_VIEW: Scope.ALL,
        Perm.COLLECTIONS_EDIT: Scope.ALL,
        Perm.SKILLS_VIEW: Scope.ALL,
        Perm.SKILLS_EDIT: Scope.ALL,
        Perm.CONTEXT_VIEW: Scope.ALL,
        Perm.CONTEXT_EDIT: Scope.ALL,
    },
    # Builder sees the whole org to learn from it, but edits only what is theirs
    # or was shared with them - so one builder cannot rewrite another's agent.
    OrgRoleName.BUILDER: {
        Perm.AGENTS_VIEW: Scope.ALL,
        Perm.AGENTS_EDIT: Scope.SHARED,
        Perm.AGENTS_PUBLISH: Scope.SHARED,
        Perm.AGENTS_RUN: Scope.ALL,
        Perm.COLLECTIONS_VIEW: Scope.ALL,
        Perm.COLLECTIONS_EDIT: Scope.SHARED,
        Perm.SKILLS_VIEW: Scope.ALL,
        Perm.SKILLS_EDIT: Scope.SHARED,
        Perm.CONTEXT_VIEW: Scope.ALL,
        Perm.CONTEXT_EDIT: Scope.SHARED,
        Perm.SECRETS_VIEW: Scope.SHARED,
        Perm.SECRETS_EDIT: Scope.OWN,
        Perm.MCP_MANAGE: Scope.ALL,
        # Both halves, spelled out. Nothing in this catalog models one permission
        # implying another - `agents:edit` does not carry `agents:view` either -
        # so a role that manages connections is given the read as well, or it
        # loses the listing it used to have.
        Perm.CONNECTIONS_VIEW: Scope.ALL,
        Perm.CONNECTIONS_MANAGE: Scope.ALL,
        Perm.RUNS_VIEW: Scope.ALL,
    },
    # Operator keeps the running system healthy: approves, watches, reruns -
    # but does not build. `connections:view` without `connections:manage` is
    # that sentence applied to the hosts: how much memory a sandbox is allowed
    # and what is running on one are answers to a page, and neither is reached
    # by anything that can point a host at a new address.
    OrgRoleName.OPERATOR: {
        Perm.AGENTS_VIEW: Scope.ALL,
        Perm.AGENTS_RUN: Scope.ALL,
        Perm.COLLECTIONS_VIEW: Scope.ALL,
        Perm.SKILLS_VIEW: Scope.ALL,
        Perm.CONTEXT_VIEW: Scope.ALL,
        Perm.SECRETS_VIEW: Scope.SHARED,
        Perm.APPROVALS_DECIDE: Scope.ALL,
        Perm.CONNECTIONS_VIEW: Scope.ALL,
        Perm.RUNS_VIEW: Scope.ALL,
    },
    # Member is the everyday user: builds their own agents, sees nobody else's
    # unless it was shared.
    OrgRoleName.MEMBER: {
        Perm.AGENTS_VIEW: Scope.SHARED,
        Perm.AGENTS_EDIT: Scope.OWN,
        Perm.AGENTS_RUN: Scope.SHARED,
        Perm.COLLECTIONS_VIEW: Scope.SHARED,
        Perm.COLLECTIONS_EDIT: Scope.OWN,
        Perm.SKILLS_VIEW: Scope.SHARED,
        Perm.SKILLS_EDIT: Scope.OWN,
        Perm.CONTEXT_VIEW: Scope.SHARED,
        Perm.CONTEXT_EDIT: Scope.OWN,
        Perm.SECRETS_VIEW: Scope.SHARED,
        Perm.SECRETS_EDIT: Scope.OWN,
    },
    OrgRoleName.VIEWER: {
        Perm.AGENTS_VIEW: Scope.SHARED,
        Perm.COLLECTIONS_VIEW: Scope.SHARED,
        Perm.SKILLS_VIEW: Scope.SHARED,
        Perm.CONTEXT_VIEW: Scope.SHARED,
    },
}


def role_has(role: str, permission: Perm) -> bool:
    """Whether a role holds a permission, ignoring resource scope.

    For code that has a role string but no request - a service checking what the
    *other* party may do, a background job reasoning about a stored membership.
    Call sites check permissions rather than role names for the same reason
    endpoints do: adding a role should never mean editing an authorization
    check.
    """
    return ROLE_PERMS.get(role, {}).get(permission, Scope.NONE) is not Scope.NONE


def _reaches(holder: dict[Perm, Scope], offered: dict[Perm, Scope]) -> bool:
    """Whether `holder` holds everything `offered` does, at least as widely."""
    return all(holder.get(perm, Scope.NONE) >= scope for perm, scope in offered.items())


def assignable_roles(role: str) -> frozenset[str]:
    """The roles a member holding `role` may hand out.

    A role may only assign one whose authority it *strictly* exceeds: every
    permission the offered role holds, held at least as widely by the assigner,
    and something the assigner holds that the offered role does not. So nobody
    assigns their own level - promoting a peer to it is an ownership decision,
    not a management one - and nobody at all assigns `owner`, since no role
    outranks it. Ownership moves through
    :meth:`app.services.member.MemberService.transfer_ownership`, which demotes
    the outgoing owner in the same breath.

    Derived from the catalog rather than from a role name, which is the whole
    point: the ceiling this replaced compared against the literal `"admin"`, so
    a custom role (Phase 2) holding `roles:manage` passed it unseen and could
    mint a second owner (#672). An unknown role holds nothing and so may assign
    nothing.
    """
    held = ROLE_PERMS.get(role, {})
    return frozenset(
        name
        for name, perms in ROLE_PERMS.items()
        if _reaches(held, perms) and not _reaches(perms, held)
    )


# The role an anonymous context carries. Deliberately not a member of
# :class:`OrgRoleName` and deliberately not a key of `ROLE_PERMS`, so it
# cannot pick up permissions from a later edit to either.
_NO_ROLE = "anonymous"


@dataclass(frozen=True)
class AuthContext:
    """Who is asking, in which organization, and what that lets them do.

    Built once per request by :func:`app.api.deps.get_auth_context` and passed
    to whatever needs to make a decision, so a route never re-derives it.

    `user_id` is optional, and that is a statement rather than a convenience.
    Every run on this platform has a subject - budgets, resource grants, the
    audit trail and the approval gate all key on one, and
    :mod:`app.services.channels.mentions` refuses an unlinked chat identity for
    exactly that reason. A surface open to anonymous visitors breaks the
    invariant, and the honest answer is to make its absence visible in the type
    so every consumer has to handle it, rather than to invent a fallback user
    whose runs nobody could be held to. What such a run *is* accountable to is
    the exposure that admitted it.
    """

    user_id: UUID | None
    organization_id: UUID
    role: str
    is_app_admin: bool = False

    channel_identity_id: UUID | None = None
    """The chat account that asked, when the asker is not a person.

    Beside `user_id` rather than instead of it, because in a group chat the two
    are different answers: the turn runs as the binding's creator, and this is
    who typed it. It decides nothing - no permission reads it - and travels here
    only because every consumer that opens a run already holds this object
    (#639).
    """

    @classmethod
    def anonymous(cls, organization_id: UUID) -> AuthContext:
        """A context for a visitor nobody can name.

        The single constructor for one, so "where can a subject-less context
        come from" is a grep rather than an audit. It holds no permission and
        reaches no row; whatever such a run is allowed to do comes from the
        exposure that admitted it, which was created by somebody who *did* have
        a role.
        """
        return cls(user_id=None, organization_id=organization_id, role=_NO_ROLE)

    @property
    def is_anonymous(self) -> bool:
        """Whether there is a person behind this context."""
        return self.user_id is None

    @property
    def subject_id(self) -> UUID:
        """The person this context is, for work that cannot be done by nobody.

        Most of what a service does keys on a person: an audit entry names an
        actor, an approval names who decided it, and a listing of "mine plus
        what was shared with me" is meaningless without a me. Those call sites
        read this instead of :attr:`user_id`, which keeps their typing honest
        and - more usefully - makes "this needs a person" something the code
        says rather than assumes.

        Raises:
            AuthorizationError: If there is no subject. Loudly, and here: an
                authenticated path that reached this far has a person, and
                letting the absence travel writes an entry naming nobody -
                indistinguishable from the two writers that legitimately name
                nobody, and by then the request has half happened. A caller
                that genuinely has no session reads :attr:`user_id` instead,
                deliberately.
        """
        if self.user_id is None:
            raise AuthorizationError(
                message="This needs a signed-in subject, and this request has none",
                details={"org_id": str(self.organization_id)},
            )
        return self.user_id

    @property
    def permissions(self) -> dict[Perm, Scope]:
        """Effective permissions from the role alone, before resource grants.

        A context with no subject holds nothing, whatever its role says. The
        check is on the subject rather than on the role string because a role is
        just a string: a subject-less context built with `"owner"` would
        otherwise reach every row in the organization, and nothing structural
        would have stopped it.

        A platform superadmin gets everything: they administer the deployment
        and already have database access - pretending otherwise would be
        security theatre, and the audit log is what actually holds them to it.
        """
        if self.is_anonymous:
            return {}
        if self.is_app_admin:
            return dict.fromkeys(Perm, Scope.ALL)
        return dict(ROLE_PERMS.get(self.role, {}))

    def scope_for(self, perm: Perm) -> Scope:
        """How far this permission reaches, or `Scope.NONE` if not held."""
        return self.permissions.get(perm, Scope.NONE)

    def has(self, perm: Perm) -> bool:
        """Whether the permission is held at all, at any scope.

        For a resource permission this only says "may touch this kind of thing";
        whether they may touch *a given row* is
        :func:`app.services.access.resolve_access`.
        """
        return self.scope_for(perm) is not Scope.NONE
