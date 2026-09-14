"""The audit export, against Postgres.

The claims a mocked session cannot make: that the file holds exactly the entries
inside the window, that a neighbour organization's entries never reach it, that
`details` survives the round trip through JSONB and out into both documents, and
that reading the whole trail is itself recorded.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import audit_log_repo
from app.services.audit import AuditService

pytestmark = pytest.mark.anyio

_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
_FROM = _NOW - timedelta(days=30)
_TO = _NOW + timedelta(days=1)


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org


async def _entry(db, org: Organization, actor: User, *, action: str, when: datetime) -> None:
    db.add(
        AppAdminAuditLog(
            id=uuid.uuid4(),
            actor_user_id=actor.id,
            organization_id=org.id,
            action=action,
            target_type="agent",
            target_id=str(uuid.uuid4()),
            details={"version": 3},
            created_at=when,
        )
    )
    await db.flush()


def _ctx(org: Organization, user: User) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)


async def test_the_export_holds_the_window_and_excludes_a_neighbour(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner)
    other_owner = await _user(db)
    other = await _org(db, other_owner)

    await _entry(db, org, owner, action="agent.published", when=_NOW)
    await _entry(db, org, owner, action="agent.ancient", when=_FROM - timedelta(days=1))
    await _entry(db, other, other_owner, action="agent.neighbour", when=_NOW)

    result = await AuditService(db).export(_ctx(org, owner), since=_FROM, until=_TO, fmt="csv")

    rows = list(csv.reader(io.StringIO(result.content)))
    actions = {row[4] for row in rows[1:]}
    assert actions == {"agent.published"}
    assert result.row_count == 1


async def test_jsonl_keeps_details_a_nested_object_through_jsonb(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner)
    await _entry(db, org, owner, action="agent.published", when=_NOW)

    result = await AuditService(db).export(_ctx(org, owner), since=_FROM, until=_TO, fmt="jsonl")

    record = json.loads(result.content.splitlines()[0])
    assert record["action"] == "agent.published"
    assert record["details"] == {"version": 3}


async def test_the_total_is_the_whole_window_not_the_limited_slice(db) -> None:
    """`count(*) OVER()` counts the full match before the LIMIT, so the cap guard
    sees the real total and refuses rather than truncating - and both come from one
    snapshot, not a count and a select that could disagree."""
    owner = await _user(db)
    org = await _org(db, owner)
    for offset in range(3):
        await _entry(db, org, owner, action="agent.published", when=_NOW - timedelta(hours=offset))

    entries, total = await audit_log_repo.list_in_window_for_org(
        db, organization_id=org.id, since=_FROM, until=_TO, limit=1
    )

    assert len(entries) == 1
    assert total == 3


async def test_reading_the_trail_is_itself_recorded(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner)
    await _entry(db, org, owner, action="agent.published", when=_NOW)

    await AuditService(db).export(_ctx(org, owner), since=_FROM, until=_TO, fmt="csv")

    # Read without the window: the export's own entry is stamped `now()`, which is
    # outside the historical window the export itself asked for.
    entries = await audit_log_repo.list_for_org(db, organization_id=org.id, limit=100)
    exports = [entry for entry in entries if entry.action == "audit.export"]
    assert len(exports) == 1
    assert exports[0].details["format"] == "csv"
    assert exports[0].details["row_count"] == 1
