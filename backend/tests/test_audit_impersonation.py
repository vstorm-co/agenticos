"""An impersonated action names who was really acting.

Impersonation issues a token whose `sub` is the target account, so without this
every row it writes and every action it records is attributed to the person it
was done *to*. The `act` claim on the token carries the administrator, the auth
dependency puts it on the request's audit context, and `record_audit` writes it
beside the actor - so the trail answers "who read this customer's conversation"
rather than pointing at the customer (#943).
"""

from __future__ import annotations

import uuid

import pytest

from app.api.deps import _impersonator_from
from app.core.audit import record_audit, set_impersonator
from app.core.security import create_access_token
from app.core.security import verify_token as _verify_token

pytestmark = pytest.mark.anyio


class _CapturingDB:
    """A session that keeps what was added, so a test can read the entry back."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, entry: object) -> None:
        self.added.append(entry)

    async def flush(self) -> None:
        pass


class TestReadingTheActorFromAToken:
    def test_an_ordinary_token_has_no_actor_behind_it(self) -> None:
        assert _impersonator_from({"sub": "user"}) is None

    def test_an_impersonation_token_names_its_actor(self) -> None:
        admin = uuid.uuid4()
        assert _impersonator_from({"sub": "target", "act": str(admin)}) == admin

    def test_a_malformed_actor_claim_is_dropped_rather_than_trusted(self) -> None:
        """A garbage `act` is no actor; the request is still attributable to its
        subject rather than refused."""
        assert _impersonator_from({"sub": "target", "act": "not-a-uuid"}) is None


class TestRecordingWhoWasActing:
    def teardown_method(self) -> None:
        set_impersonator(None)

    async def test_an_impersonated_action_records_the_administrator_behind_it(self) -> None:
        admin, target = uuid.uuid4(), uuid.uuid4()
        set_impersonator(admin)

        db = _CapturingDB()
        await record_audit(db, actor_user_id=target, action="agent.deleted")

        entry = db.added[0]
        assert entry.actor_user_id == target
        assert entry.impersonator_user_id == admin

    async def test_an_ordinary_action_records_no_impersonator(self) -> None:
        set_impersonator(None)

        db = _CapturingDB()
        await record_audit(db, actor_user_id=uuid.uuid4(), action="agent.published")

        assert db.added[0].impersonator_user_id is None

    async def test_acting_as_oneself_is_not_recorded_as_impersonation(self) -> None:
        """`act` equal to the actor is nobody impersonating anybody, so the
        impersonator stays null rather than naming the actor twice."""
        me = uuid.uuid4()
        set_impersonator(me)

        db = _CapturingDB()
        await record_audit(db, actor_user_id=me, action="agent.published")

        assert db.added[0].impersonator_user_id is None

    async def test_the_claim_survives_from_the_token_into_the_entry(self) -> None:
        """The whole chain #943 turns on: a minted impersonation token, decoded,
        read onto the audit context, and recorded on the action it produces."""
        admin, target = uuid.uuid4(), uuid.uuid4()
        payload = _verify_token(create_access_token(str(target), act=str(admin)))
        assert payload is not None
        set_impersonator(_impersonator_from(payload))

        db = _CapturingDB()
        await record_audit(db, actor_user_id=target, action="conversation.read")

        assert db.added[0].impersonator_user_id == admin


class TestNestedImpersonation:
    def teardown_method(self) -> None:
        set_impersonator(None)

    async def test_a_nested_impersonation_names_the_human_who_started_the_chain(self) -> None:
        """A impersonates app-admin B, whose token impersonates C. The minted
        token must keep naming A, not B - or the chain launders A out of the audit
        trail one hop at a time (#943)."""
        from unittest.mock import AsyncMock, MagicMock

        from app.api.routes.v1.admin_users import impersonate_user
        from app.core.security import verify_token

        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        set_impersonator(a)  # this request runs on B's token, itself impersonated by A

        admin = MagicMock(id=b)
        target = MagicMock(id=c, email="c@example.com")
        service = MagicMock(get_by_id=AsyncMock(return_value=target))
        request = MagicMock(client=MagicMock(host="1.2.3.4"))

        response = await impersonate_user(request, c, admin, _CapturingDB(), service)

        payload = verify_token(response.access_token)
        assert payload is not None
        assert payload["sub"] == str(c)
        assert payload["act"] == str(a)
