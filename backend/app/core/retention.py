"""How long a class of data lives here, and who gets to say.

Nothing was ever deleted on a schedule before this. Conversations, their files,
run rows and manifests, workspaces, memory and audit entries lived until
somebody deleted the whole organization - which is a data-protection problem in
one direction and, for audit, a compliance problem in the other. Two standards
pull opposite ways and both need a setting: HIPAA wants audit records kept six
years, GDPR wants everything else minimised (#1420).

So retention is **per class**, and the classes are the ones a person would name
when asked what to keep: what was said, what was run, what an agent kept, what
was uploaded, and the trail of who changed what.

Three layers decide the number, and this module is the only place they meet:

1. **The deployment's default** - what an organization gets before it has an
   opinion. Absent means "for ever", because a platform that silently started
   deleting an existing installation's history on upgrade would be a platform
   nobody could trust with the next upgrade either.
2. **The organization's own setting** - shorter or longer, within the ceiling.
3. **The deployment's ceiling** - "nothing lives longer than N days here",
   which an organization cannot raise.

And audit runs the other way round: the deployment sets a **floor**, and an
organization may lengthen it and never shorten it. A trail an administrator can
shorten is not a trail.

A floor above a ceiling is a contradiction, not a tie to break quietly, so
`policy_conflicts` reports it and the settings that would create one are
refused. Choosing one of the two would give an operator a deployment whose
behaviour disagrees with its own settings page.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

RetentionClass = Literal[
    "conversations",
    "runs",
    "workspaces",
    "memory",
    "knowledge_documents",
    "audit",
]
"""What a period can be set on. The order is the order the settings page shows."""

RETENTION_CLASSES: Final[tuple[RetentionClass, ...]] = get_args(RetentionClass)

AUDIT: Final[RetentionClass] = "audit"
"""Named, because it is the one class whose deployment setting is a floor."""

DEFAULT_AUDIT_FLOOR_DAYS: Final[int] = 2190
"""Six years, which is what HIPAA §164.316(b)(2) asks of an audit record.

The built-in when a deployment has set none. A deployment under a longer
obligation raises it; one under none may lower it, which is a deliberate act
with a number attached rather than a silent absence of one.
"""

MIN_RETENTION_DAYS: Final[int] = 1
MAX_RETENTION_DAYS: Final[int] = 36500
"""A hundred years. Not a policy - a bound, so a typo cannot overflow a date."""

#: A period read off a policy: days, or None for "keep for ever".
Days = int | None

#: A policy as it is stored - a period per class, classes absent where unset.
Policy = dict[str, Days]


def effective_policy(
    *,
    organization: Policy | None,
    defaults: Policy | None,
    ceilings: Policy | None,
    audit_floor_days: int | None,
) -> dict[RetentionClass, Days]:
    """What actually gets swept, per class, after all three layers.

    Args:
        organization: The organization's own periods, where it has set any.
        defaults: The deployment's defaults for an organization that has not.
        ceilings: The deployment's per-class maximum. An organization asking for
            longer gets the ceiling; one that set nothing and whose deployment
            default is longer gets the ceiling too, because a ceiling is a
            statement about the deployment rather than about who configured what.
        audit_floor_days: The deployment's audit floor, or None for the built-in.

    Returns:
        Every class, with the number of days its rows live or None for for ever.
        A class nobody has an opinion about is None everywhere except `audit`,
        which always has a floor and so always has a number.
    """
    org = organization or {}
    default = defaults or {}
    ceiling = ceilings or {}
    floor = audit_floor_days if audit_floor_days is not None else DEFAULT_AUDIT_FLOOR_DAYS

    resolved: dict[RetentionClass, Days] = {}
    for name in RETENTION_CLASSES:
        chosen = org[name] if name in org else default.get(name)
        if name == AUDIT:
            # A floor, not a default: the longer of the two wins, and an
            # organization that set nothing still gets the floor.
            resolved[name] = floor if chosen is None else max(chosen, floor)
            continue
        cap = ceiling.get(name)
        if cap is not None and (chosen is None or chosen > cap):
            chosen = cap
        resolved[name] = chosen
    return resolved


def policy_conflicts(
    *, ceilings: Policy | None, audit_floor_days: int | None
) -> list[RetentionClass]:
    """The classes whose deployment settings contradict each other.

    One shape today and it is the important one: an audit ceiling below the audit
    floor, which asks for a trail that must be kept six years and deleted after
    one. Reported rather than resolved - an operator who set both meant one of
    them, and the settings page is where they say which.
    """
    ceiling = (ceilings or {}).get(AUDIT)
    floor = audit_floor_days if audit_floor_days is not None else DEFAULT_AUDIT_FLOOR_DAYS
    return [AUDIT] if ceiling is not None and ceiling < floor else []


def known_periods(stored: Policy | None) -> dict[RetentionClass, Days]:
    """A stored mapping narrowed to the classes this version knows about.

    JSONB holds whatever was written, and a class renamed or removed in a later
    version would otherwise surface in an API response as a period for something
    that no longer exists. The row keeps it - it is not this function's to
    delete - but nothing downstream sees it.
    """
    held = stored or {}
    return {name: held[name] for name in RETENTION_CLASSES if name in held}
