"""Who may act on a run's approval, and who may open their own run.

One module so that every place asking "may this person decide that run?" asks
the same question: the decision itself, the decide link in a notification, the
expiry notice and the run the notice opens. It imports nothing from the
services that use it, so the notification code can share it with the approval
service without an import cycle.
"""

from typing import Final
from uuid import UUID

from app.core.audit import current_impersonator
from app.core.permissions import AuthContext, Perm, Scope
from app.db.models.agent_run import CHANNEL_SURFACES, AgentRun, RunSurface

# The surfaces an own-run decision may come from: the web console, and the
# chats a run can be continued in. Anything else - an API call, a schedule, a
# workflow step, an evaluation, an embedded widget running as its publisher -
# has no signed-in person at the keyboard, so the exception does not reach it.
_OWN_RUN_SURFACES: Final = frozenset(
    {RunSurface.WEB.value, *(surface.value for surface in CHANNEL_SURFACES)}
)


def signed_in_person(ctx: AuthContext) -> bool:
    """Whether this caller is a person at the keyboard, not a credential acting for one.

    A session, not a key: an API key's issuer may have started the run, but a
    key is a script, and a script deciding its own approval is the agent
    approving itself. A publisher fallback, a fired routine and an impersonated
    session are the same shape - somebody other than the person the run
    belongs to - so they are out too.
    """
    return (
        ctx.user_id is not None
        and ctx.api_key_id is None
        and ctx.key_scopes is None
        and not ctx.subject_is_publisher_fallback
        and ctx.fired_as_creator is None
        and ctx.routine_id is None
        and current_impersonator() is None
    )


def starter_of(run: AgentRun | None) -> UUID | None:
    """The person who started this run, when the run was theirs to start.

    The stored `run.user_id`, never anything the caller sends. A run on a
    surface with no person at the keyboard, or one a publisher's fallback
    identity ran for a stranger, has no starter in this sense: it carries the
    publisher's id but was started by somebody else.
    """
    if (
        run is None
        or run.user_id is None
        or run.initiated_by_publisher_fallback
        or run.surface not in _OWN_RUN_SURFACES
    ):
        return None
    return run.user_id


def stored_starter_id(value: object) -> UUID | None:
    """The starter a notification stored in its context, or `None` if it holds none.

    Rows written before the starter was stored carry nothing, and a value that is
    not an id is read as nothing: the link-less summary, which is the safe direction.
    """
    try:
        return UUID(str(value)) if value is not None else None
    except ValueError:
        return None


def decides_as_starter(ctx: AuthContext, starter_id: UUID | None) -> bool:
    """Whether this caller is the starter and may still decide at all.

    The own-run exception: a member or builder holds `approvals:decide` at
    `OWN`, and the ownership is enforced here, not in the role - a role cannot
    see which run an approval belongs to, and `AuthContext.has` alone cannot
    tell `OWN` from `ALL`. A member demoted to viewer after starting a run
    loses the decision with the permission, rather than keeping it on
    ownership alone.
    """
    return (
        starter_id is not None
        and starter_id == ctx.user_id
        and ctx.has(Perm.APPROVALS_DECIDE)
        and signed_in_person(ctx)
    )


def may_decide_approval(ctx: AuthContext, run: AgentRun | None) -> bool:
    """Whether this caller may decide an approval on this run.

    Two ways in, and they are deliberately not the same authority:

    - a privileged decider - `approvals:decide` at `ALL`, the owner, admin and
      operator - may decide any run's approval, as before;
    - anybody else only on a run *they* started, from a signed-in web or chat
      session (see :func:`decides_as_starter`).

    A run nobody can name (`None`) is decidable by nobody the second way.
    """
    return ctx.scope_for(Perm.APPROVALS_DECIDE) is Scope.ALL or decides_as_starter(
        ctx, starter_of(run)
    )


def may_follow_decision_link(ctx: AuthContext, starter_id: UUID | None) -> bool:
    """Whether a notification may hand this reader a link to decide a run.

    `starter_id` is what the notification stored when it was written, and it is
    stored only for a run whose starter :func:`starter_of` names. The answer is
    the one :func:`may_decide_approval` gives, so a link is never offered to a
    reader the decision would refuse.
    """
    return ctx.scope_for(Perm.APPROVALS_DECIDE) is Scope.ALL or decides_as_starter(ctx, starter_id)


def may_waive_own_run(ctx: AuthContext) -> bool:
    """Whether this caller may waive approvals for a run they start.

    The advance form of the own-run exception: a standing consent *is* the
    decision the approval queue exists to record, so the same person has to
    stand behind it - a signed-in person holding `approvals:decide` at any
    scope, starting their own run. A key, a routine, a publisher fallback or
    an impersonated session may not waive, even when the role behind it could.
    The web-chat surface and the organization's waiver switch are checked
    where this is used, not here.
    """
    return ctx.has(Perm.APPROVALS_DECIDE) and signed_in_person(ctx)


def may_open_own_run(ctx: AuthContext, run: AgentRun) -> bool:
    """Whether this caller may open, read and retry this run without `runs:view`.

    The starter's own way back to a run whose approval expired, held to the same
    predicate as the decision (:func:`decides_as_starter`): the starter by the
    stored `run.user_id`, from a signed-in session, in an active membership, and
    still holding `approvals:decide`. The run is open to them because they need
    it to decide - a starter demoted to viewer or removed from the organization
    loses it with the permission. It never widens to `runs:view`, which would
    show every run in the organization. A key, a routine, a publisher fallback,
    an impersonated session and an unattended surface are refused.
    """
    return bool(ctx.role) and decides_as_starter(ctx, starter_of(run))
