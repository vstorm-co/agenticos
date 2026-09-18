"""Decision 1's catalog: mandatory-ness and the read-time content gate (#1598)."""

from __future__ import annotations

from app.db.models.notification import NotificationEventType
from app.services.notification_catalog import (
    CONTENT_GATE,
    MANDATORY_EVENT_TYPES,
    ContentGate,
    content_gate_for,
    is_mandatory,
)


class TestMandatoryEventTypes:
    def test_security_and_configuration_events_are_mandatory(self):
        assert {
            NotificationEventType.SECURITY_EVENT,
            NotificationEventType.CONFIGURATION_CHANGED,
        } == MANDATORY_EVENT_TYPES
        assert is_mandatory(NotificationEventType.SECURITY_EVENT) is True
        assert is_mandatory(NotificationEventType.CONFIGURATION_CHANGED) is True

    def test_every_other_event_type_is_not_mandatory(self):
        for event_type in NotificationEventType:
            if event_type in MANDATORY_EVENT_TYPES:
                continue
            assert is_mandatory(event_type) is False


class TestContentGate:
    def test_an_event_with_no_gate_defaults_to_none(self):
        for event_type in (
            NotificationEventType.BUDGET_EXCEEDED,
            NotificationEventType.RUN_COMPLETED,
            NotificationEventType.RUN_FAILED,
        ):
            assert event_type not in CONTENT_GATE
            assert content_gate_for(event_type) is ContentGate.NONE

    def test_every_catalogued_event_type_resolves_to_its_gate(self):
        expected = {
            NotificationEventType.APPROVAL_REQUESTED: ContentGate.DEGRADE,
            NotificationEventType.USAGE_REPORT: ContentGate.RUNS_VIEW,
            NotificationEventType.AGENT_USAGE_REPORT: ContentGate.RUNS_VIEW,
            NotificationEventType.INGESTION_COMPLETED: ContentGate.COLLECTIONS_VIEW,
            NotificationEventType.INGESTION_FAILED: ContentGate.COLLECTIONS_VIEW,
            NotificationEventType.SECURITY_EVENT: ContentGate.ORG_ADMIN_OR_APP_ADMIN,
            NotificationEventType.CONFIGURATION_CHANGED: ContentGate.APP_ADMIN,
            NotificationEventType.ANNOUNCEMENT: ContentGate.ANNOUNCEMENT_AUDIENCE,
        }
        for event_type, gate in expected.items():
            assert content_gate_for(event_type) is gate
