"""HubSpot and Zendesk as event sources: their signatures, filters and context."""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import AuthorizationError
from app.schemas.agent_trigger import TriggerCreate, webhook_url
from app.services import trigger_events
from app.services.agent_trigger import AgentTriggerService
from app.services.rate_limit import Decision

pytestmark = pytest.mark.anyio

_SECRET = "a-provider-issued-secret"
_URL = "https://api.example.test/api/v1/webhooks/triggers/hubspot/t1"
_NOW = 1_800_000_000.0
_EVENT = {
    "eventId": 101,
    "subscriptionId": 7,
    "portalId": 42,
    "occurredAt": 1_799_999_990_000,
    "subscriptionType": "deal.propertyChange",
    "attemptNumber": 0,
    "objectId": 9001,
    "propertyName": "dealstage",
    "propertyValue": "closedwon",
}


def _b64_hmac(signed: bytes) -> str:
    return base64.b64encode(hmac.new(_SECRET.encode(), signed, hashlib.sha256).digest()).decode()


def _hubspot_v3(body: bytes, *, url: str = _URL, at_ms: int = int(_NOW * 1000)) -> dict[str, str]:
    stamp = str(at_ms)
    return {
        "x-hubspot-signature-v3": _b64_hmac(b"POST" + url.encode() + body + stamp.encode()),
        "x-hubspot-request-timestamp": stamp,
    }


def _zendesk(body: bytes, *, stamp: str = "2027-01-15T08:00:00Z") -> dict[str, str]:
    return {
        "x-zendesk-webhook-signature": _b64_hmac(stamp.encode() + body),
        "x-zendesk-webhook-signature-timestamp": stamp,
    }


_ZENDESK_NOW = datetime(2027, 1, 15, 8, 1, tzinfo=UTC).timestamp()


def _verify(
    source: str, body: bytes, headers: dict[str, str], *, url: str | None = _URL, now: float = _NOW
):
    return trigger_events.verify_signature(
        source, secret=_SECRET, body=body, headers=headers, url=url, now=now
    )


class TestHubspotSignature:
    body = json.dumps([_EVENT]).encode()

    def test_a_v3_signature_over_the_url_it_was_given_verifies(self):
        assert _verify("hubspot", self.body, _hubspot_v3(self.body))

    @pytest.mark.security
    def test_a_v3_signature_for_another_url_or_body_fails(self):
        """The URL is in the signed string, so a delivery for one trigger cannot be
        replayed at another's door."""
        other = _hubspot_v3(self.body, url=_URL.replace("t1", "t2"))
        assert not _verify("hubspot", self.body, other)
        assert not _verify("hubspot", self.body + b" ", _hubspot_v3(self.body))
        # A caller that cannot say which URL it handed out cannot verify v3 at all.
        assert not _verify("hubspot", self.body, _hubspot_v3(self.body), url=None)

    @pytest.mark.security
    def test_a_v3_timestamp_older_than_five_minutes_fails(self):
        stale = _hubspot_v3(self.body, at_ms=int((_NOW - 301) * 1000))
        assert not _verify("hubspot", self.body, stale)
        malformed = {**_hubspot_v3(self.body), "x-hubspot-request-timestamp": "soon"}
        assert not _verify("hubspot", self.body, malformed)

    def test_a_v1_signature_verifies_where_hubspot_sends_only_that(self):
        """CRM object subscriptions are still signed v1: SHA-256 of secret and body."""
        headers = {
            "x-hubspot-signature-version": "v1",
            "x-hubspot-signature": hashlib.sha256(_SECRET.encode() + self.body).hexdigest(),
        }
        assert _verify("hubspot", self.body, headers)
        assert not _verify("hubspot", self.body, {**headers, "x-hubspot-signature": "0" * 64})

    def test_no_signature_or_another_version_fails(self):
        assert not _verify("hubspot", self.body, {})
        legacy = {"x-hubspot-signature-version": "v2", "x-hubspot-signature": "x"}
        assert not _verify("hubspot", self.body, legacy)


class TestZendeskSignature:
    body = b'{"type": "zen:event-type:ticket.created"}'

    def test_a_signature_over_the_timestamp_and_body_verifies(self):
        assert _verify("zendesk", self.body, _zendesk(self.body), now=_ZENDESK_NOW)

    @pytest.mark.security
    @pytest.mark.parametrize("stamp", ["2027-01-15T07:50:00Z", "2027-01-15T08:00:00", "yesterday"])
    def test_a_stale_naive_or_unreadable_timestamp_fails(self, stamp):
        assert not _verify("zendesk", self.body, _zendesk(self.body, stamp=stamp), now=_ZENDESK_NOW)

    def test_a_signature_for_another_body_fails(self):
        assert not _verify("zendesk", b"{}", _zendesk(self.body), now=_ZENDESK_NOW)


class TestDeliveryIds:
    def test_a_hubspot_batch_is_known_by_its_events_whatever_attempt_it_is(self):
        """Each retry bumps `attemptNumber`, so the body is not the batch's identity."""
        first = trigger_events.delivery_id("hubspot", {}, {"events": [_EVENT]})
        retry = trigger_events.delivery_id(
            "hubspot", {}, {"events": [{**_EVENT, "attemptNumber": 3}]}
        )
        other = trigger_events.delivery_id("hubspot", {}, {"events": [{**_EVENT, "eventId": 102}]})
        assert first is not None and first.startswith("hubspot:")
        assert first == retry
        assert first != other
        assert trigger_events.delivery_id("hubspot", {}, {"events": []}) is None

    def test_zendesk_is_known_by_its_invocation_id(self):
        headers = {"x-zendesk-webhook-invocation-id": "inv-1"}
        assert trigger_events.delivery_id("zendesk", headers, {}) == "inv-1"


class TestMatching:
    def test_a_hubspot_batch_fires_when_any_event_in_it_passes(self):
        batch = {"events": [{**_EVENT, "subscriptionType": "contact.creation"}, _EVENT, "noise"]}

        def matches(config: dict[str, object]) -> bool:
            return trigger_events.event_matches("hubspot", headers={}, payload=batch, config=config)

        assert matches({})
        assert matches(
            {"subscription_types": ["deal.propertyChange"], "property_names": ["dealstage"]}
        )
        assert not matches({"subscription_types": ["ticket.creation"]})
        assert not matches(
            {"subscription_types": ["deal.propertyChange"], "property_names": ["amount"]}
        )

    def test_a_zendesk_event_type_is_matched_exactly_and_a_rule_body_only_without_one(self):
        def matches(payload: dict[str, object], config: dict[str, object]) -> bool:
            return trigger_events.event_matches(
                "zendesk", headers={}, payload=payload, config=config
            )

        created = {"type": "zen:event-type:ticket.created"}
        assert matches(created, {"event_types": ["zen:event-type:ticket.created"]})
        assert not matches(created, {"event_types": ["zen:event-type:ticket.status_changed"]})
        # A Zendesk rule's own body names no event: the rule already chose when to call.
        assert matches({"ticket": 5}, {})
        assert not matches({"ticket": 5}, {"event_types": ["zen:event-type:ticket.created"]})

    def test_an_unknown_filter_key_is_refused(self):
        with pytest.raises(PydanticValidationError):
            TriggerCreate(
                prompt="p",
                trigger_type="event",
                event_source="zendesk",
                event_secret="s" * 32,
                event_config={"ticket_status": "open"},
            )


class TestContext:
    def test_a_hubspot_batch_lists_its_events_and_bounds_the_list(self):
        rendered = trigger_events.render_context(
            "hubspot", payload={"events": [_EVENT, {**_EVENT, "propertyName": None}] * 11}
        )
        assert rendered.startswith("Events from HubSpot (22):")
        assert "- deal.propertyChange on object 9001: dealstage = closedwon (portal 42" in rendered
        assert "...and 2 more." in rendered

    def test_a_zendesk_delivery_names_its_event_or_says_it_came_from_a_rule(self):
        event = trigger_events.render_context(
            "zendesk", payload={"type": "zen:event-type:ticket.created", "detail": {"id": "5"}}
        )
        assert event.startswith("A Zendesk event arrived: zen:event-type:ticket.created.")
        assert '"id": "5"' in event
        rule = trigger_events.render_context("zendesk", payload={"ticket": 5})
        assert rule.startswith("A Zendesk webhook arrived.")


class TestTheDoor:
    """Through `prepare_event_fire`, with the real verifier: the URL the signature
    is checked against is the one the trigger handed out."""

    async def test_a_signed_hubspot_batch_fires_with_its_events(self):
        trigger_id = uuid.uuid4()
        trigger = MagicMock(
            id=trigger_id,
            organization_id=uuid.uuid4(),
            trigger_type="event",
            event_source="hubspot",
            is_active=True,
            event_config={"subscription_types": ["deal.propertyChange"]},
        )
        body = json.dumps([_EVENT]).encode()
        service = AgentTriggerService(MagicMock())
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.unseal", return_value=_SECRET),
            patch(
                "app.services.agent_trigger.rate_limit.trigger_delivery_allowed",
                AsyncMock(return_value=Decision(allowed=True, retry_after_seconds=0)),
            ),
            patch.object(AgentTriggerService, "_claim", AsyncMock(return_value=True)),
            patch("app.services.trigger_events.time.time", return_value=_NOW),
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            headers = _hubspot_v3(body, url=webhook_url("hubspot", trigger_id))
            decision = await service.prepare_event_fire(
                "hubspot", trigger_id, body=body, headers=headers
            )
            assert decision is not None
            assert decision.event_context.startswith("Events from HubSpot (1):")

            # The same delivery signed for another trigger's URL is a 403.
            forged = _hubspot_v3(body, url=webhook_url("hubspot", uuid.uuid4()))
            with pytest.raises(AuthorizationError):
                await service.prepare_event_fire("hubspot", trigger_id, body=body, headers=forged)
