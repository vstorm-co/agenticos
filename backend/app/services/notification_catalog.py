"""Decision 1's event catalog: which events are mandatory, and how a reader's
current standing re-gates one at read time (#1598).

`docs/design/notification-center-plan.md` names this catalog as a table in
code, not a form an admin fills in - a developer adds a row when a new event
ships. This module is deliberately narrower than the full table the design
doc draws: it carries only what the write path and the inbox routes need
*now* (mandatory-ness, and the read-time content gate), not each event's
producer or default audience, which are decided at each producer's own call
site as later phases wire them in.
"""

from __future__ import annotations

import enum

from app.db.models.notification import NotificationEventType


class ContentGate(enum.Enum):
    """How a reader's *current* standing re-gates a row at read time (Decision 7).

    `NONE` needs no recheck beyond the tenant/recipient scoping every row gets.
    `DEGRADE` is `approval_requested`'s own shape - the row is always returned,
    but its `context_url` is withheld from a reader who no longer holds
    `approvals:decide`, the same "here is the fact, without the link only a
    decider can use" the existing approval email already sends a non-decider.
    Every other value **excludes** the row outright for a reader who no longer
    holds it - there is no partial truth for "you are no longer an admin" or
    "you left the audience this was sent to".
    """

    NONE = "none"
    DEGRADE = "degrade"
    ORG_ADMIN_OR_APP_ADMIN = "org_admin_or_app_admin"
    APP_ADMIN = "app_admin"
    RUNS_VIEW = "runs_view"
    COLLECTIONS_VIEW = "collections_view"
    ANNOUNCEMENT_AUDIENCE = "announcement_audience"


# Decision 1's "Content gated on" column, read by event type. A row with no
# gate here (`budget_exceeded`, `run_completed`, `run_failed`) needs no recheck
# beyond the tenant/membership check every row already gets from the read
# paths' own organization scoping.
CONTENT_GATE: dict[NotificationEventType, ContentGate] = {
    NotificationEventType.APPROVAL_REQUESTED: ContentGate.DEGRADE,
    NotificationEventType.USAGE_REPORT: ContentGate.RUNS_VIEW,
    NotificationEventType.AGENT_USAGE_REPORT: ContentGate.RUNS_VIEW,
    NotificationEventType.INGESTION_COMPLETED: ContentGate.COLLECTIONS_VIEW,
    NotificationEventType.INGESTION_FAILED: ContentGate.COLLECTIONS_VIEW,
    NotificationEventType.SECURITY_EVENT: ContentGate.ORG_ADMIN_OR_APP_ADMIN,
    NotificationEventType.CONFIGURATION_CHANGED: ContentGate.APP_ADMIN,
    NotificationEventType.ANNOUNCEMENT: ContentGate.ANNOUNCEMENT_AUDIENCE,
}

# `security_event` and `configuration_changed` bypass preference entirely on
# both channels (Decision 4) - the same shape the deployment already applies
# to the impersonation notice and the organization's own budget cap. The write
# helper also consults `services/rate_limit.py` before a write for one of
# these, keyed on `(actor_user_id, event_type)` (Decision 1's rate-limit note):
# an ordinary write access must not become an unmetered fan-out against every
# admin in an organization.
MANDATORY_EVENT_TYPES: frozenset[NotificationEventType] = frozenset(
    {NotificationEventType.SECURITY_EVENT, NotificationEventType.CONFIGURATION_CHANGED}
)


def content_gate_for(event_type: NotificationEventType) -> ContentGate:
    return CONTENT_GATE.get(event_type, ContentGate.NONE)


def is_mandatory(event_type: NotificationEventType) -> bool:
    return event_type in MANDATORY_EVENT_TYPES
