"""Reviewed account aliases remain valid after the MCP runtime normalizes them."""

from uuid import uuid4

import pytest

from app.agents.mcp import tool_prefix
from app.db.models.mcp_connection import McpConnection
from app.services.mcp_connection import reviewed_personal_sources


def test_colliding_account_labels_keep_distinct_normalized_aliases() -> None:
    accounts = [
        McpConnection(
            id=uuid4(),
            name=name,
            is_default=index == 0,
            url=f"https://account{index}.example.com",
            authorization_generation=uuid4(),
        )
        for index, name in enumerate(("Work", "Sales US", "Sales-US"))
    ]
    identities = reviewed_personal_sources("github", accounts)
    aliases = [identity.tool_prefix for identity in identities.values()]
    assert len(set(aliases)) == 3
    assert all(alias is not None and alias == tool_prefix(alias) for alias in aliases)
    assert reviewed_personal_sources("github", []) == {}


def test_starter_visibility_accepts_only_the_historical_presentation_hashes() -> None:
    import hashlib
    import json
    from datetime import UTC, datetime

    from app.agents.spec import AgentSpec
    from app.schemas.routine_sources import RoutineSourcePolicy
    from app.services.routine_sources import (
        _NON_SOURCE_FIELDS,
        RoutineSourceSnapshot,
        compatible_spec_fingerprints,
        spec_fingerprint,
    )

    spec = AgentSpec(name="Worker")
    policy = RoutineSourcePolicy(
        id=uuid4(),
        consented_by=uuid4(),
        reviewed_at=datetime.now(UTC),
        version_id=uuid4(),
        scope_hash="a" * 64,
        spec_hash=spec_fingerprint(spec),
    )
    snapshot = RoutineSourceSnapshot(
        policy=policy,
        resources=[],
        items=[],
        accounts=[],
        unavailable=[],
        compatible_spec_hashes=compatible_spec_fingerprints(spec),
    )
    material = spec.model_dump(mode="json", exclude=set(_NON_SOURCE_FIELDS))
    material.pop("table_bindings", None)
    for visible in (True, False):
        legacy = hashlib.sha256(
            json.dumps(
                {**material, "show_starters": visible}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        assert snapshot.matches_restricted(policy.model_copy(update={"spec_hash": legacy}))
    assert spec_fingerprint(spec.model_copy(update={"show_starters": False})) == policy.spec_hash
    for changed in (
        policy.model_copy(update={"spec_hash": "f" * 64}),
        policy.model_copy(update={"scope_hash": "c" * 64}),
        policy.model_copy(update={"consented_by": uuid4()}),
    ):
        assert not snapshot.matches_restricted(changed)
    changed = spec.model_copy(update={"collection_ids": [uuid4()]})
    assert not snapshot.matches_restricted(
        policy.model_copy(update={"spec_hash": spec_fingerprint(changed)})
    )


@pytest.mark.anyio
async def test_readiness_preserves_a_historical_review_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from app.agents.spec import AgentSpec
    from app.core.permissions import AuthContext, OrgRoleName
    from app.db.models.agent_trigger import AgentTrigger
    from app.services.routine_sources import (
        RoutineSourceService,
        RoutineSourceSnapshot,
        compatible_spec_fingerprints,
        spec_fingerprint,
    )
    from tests.routine_source_support import reviewed_sources

    trigger = AgentTrigger(
        id=uuid4(),
        organization_id=uuid4(),
        agent_id=uuid4(),
        created_by_user_id=uuid4(),
    )
    spec = AgentSpec(name="Worker")
    policy = reviewed_sources(trigger, spec=spec, version_id=uuid4())
    legacy_hash = next(
        value for value in compatible_spec_fingerprints(spec) if value != policy.spec_hash
    )
    trigger.approved_sources = policy.model_copy(update={"spec_hash": legacy_hash}).model_dump(
        mode="json"
    )
    before = dict(trigger.approved_sources)
    snapshot = RoutineSourceSnapshot(
        policy=policy,
        resources=[],
        items=[],
        accounts=[],
        unavailable=[],
        compatible_spec_hashes=compatible_spec_fingerprints(spec),
    )
    db = AsyncMock()
    service = RoutineSourceService(db)
    monkeypatch.setattr(service, "_review", AsyncMock(return_value=snapshot))
    assert trigger.created_by_user_id is not None
    ctx = AuthContext(
        user_id=trigger.created_by_user_id,
        organization_id=trigger.organization_id,
        role=OrgRoleName.MEMBER,
    )
    current, refreshed = await service.current(ctx, trigger, expected_id=policy.id)
    assert refreshed and current.spec_hash == spec_fingerprint(spec)
    assert trigger.approved_sources == before
    db.flush.assert_not_awaited()
    admitted = await service.require_current(ctx, trigger, expected_id=policy.id)
    assert admitted == current
    assert trigger.approved_sources["spec_hash"] == current.spec_hash
    db.flush.assert_awaited_once()
