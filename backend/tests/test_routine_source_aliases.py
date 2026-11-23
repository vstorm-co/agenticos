"""Reviewed account aliases remain valid after the MCP runtime normalizes them."""

from uuid import uuid4

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
