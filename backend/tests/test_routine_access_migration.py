"""`0366_routine_access_review.py` converts each routine in place: none gains authority, none stops.

The conversion is pure JSON to JSON, so each legacy shape is checked here
against the schema the application now reads. `tests/test_migrations.py` runs
the revision against a real database.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest

from app.schemas.routine_sources import RoutineSourcePolicy

pytestmark = pytest.mark.security


def _migration() -> ModuleType:
    path = Path(__file__).parents[1] / "alembic/versions/0366_routine_access_review.py"
    spec = importlib.util.spec_from_file_location("routine_access_review_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _migration()
VERSION = str(uuid4())
CONNECTION = str(uuid4())


def _legacy(mode: str, **extra: Any) -> dict[str, Any]:
    """A stored review as the previous schema wrote it."""
    policy: dict[str, Any] = {
        "mode": mode,
        "id": str(uuid4()),
        "consented_by": str(uuid4()),
        "reviewed_at": datetime.now(UTC).isoformat(),
        "version_id": VERSION,
        "scope_hash": "a" * 64,
        "spec_hash": "b" * 64,
        "behavior": {"capability:sandbox": "c" * 64} if mode == "follow_agent" else None,
        "mcp_sources": {
            CONNECTION: {
                "endpoint_hash": "d" * 64,
                "authorization_generation": str(uuid4()),
                "tool_prefix": None,
                "tool_ids": ["create_issue"],
            }
        },
        **extra,
    }
    if mode == "follow_agent":
        policy["approved_ceiling"] = {
            key: value for key, value in policy.items() if key != "approved_ceiling"
        }
    return policy


def _consent(version: str = VERSION, **key: str) -> dict[str, Any]:
    return {
        **(key or {"capability_id": "sandbox", "tool_id": "execute"}),
        "id": str(uuid4()),
        "consented_by": str(uuid4()),
        "version_id": version,
        "intent_hash": "e" * 64,
    }


def _convert(
    policy: dict[str, Any] | None,
    action_mode: str | None,
    consents: list[dict[str, Any]] | None = None,
    settings: list[dict[str, Any]] | None = None,
) -> RoutineSourcePolicy:
    converted = MIGRATION._review(policy, action_mode, consents or [], settings or [])
    return RoutineSourcePolicy.model_validate(converted)


@pytest.mark.parametrize(("mode", "action_mode"), [("restricted", "agent"), ("follow_agent", None)])
def test_a_routine_that_ran_as_its_agent_allows_is_grandfathered(
    mode: str, action_mode: str | None
) -> None:
    review = _convert(
        _legacy(mode),
        action_mode,
        consents=[_consent()],
        settings=[
            {"capability_id": "sandbox", "tool_id": "execute", "setting": "off"},
            {"connection_id": CONNECTION, "tool_id": "create_issue", "setting": "ask"},
        ],
    )
    assert review.mode == "reviewed"
    assert review.grandfathered is True
    assert review.delegates == "allow"
    # The owner's narrowing is kept; consent was not what released these tools.
    assert {(tool.tool_id, tool.setting) for tool in review.tools} == {
        ("execute", "off"),
        ("create_issue", "ask"),
    }
    assert review.intent_hash is None


def test_a_follow_review_keeps_its_ceiling_and_a_restricted_one_its_spec() -> None:
    following = _convert(_legacy("follow_agent"), "per_tool")
    assert following.approved_ceiling is not None
    assert following.approved_ceiling.mode == "reviewed"
    assert following.approved_ceiling.behavior == following.behavior
    restricted = _convert(_legacy("restricted"), "per_tool")
    assert restricted.approved_ceiling is None
    assert restricted.behavior is None
    assert restricted.spec_hash == "b" * 64


def test_consent_bound_to_the_reviewed_version_becomes_allow_and_stale_consent_is_dropped() -> None:
    review = _convert(
        _legacy("restricted"),
        "per_tool",
        consents=[
            _consent(),
            _consent(connection_id=CONNECTION, tool_id="create_issue"),
            _consent(kind="platform", tool_id="create_task"),
            _consent(version=str(uuid4()), capability_id="sandbox", tool_id="write_file"),
            # Unreadable: no tool, or no kind of key.
            _consent(capability_id="sandbox", tool_id=None),
            _consent(tool_id="orphan"),
        ],
        settings=[
            # An owner's narrowing wins over a consent to the same tool.
            {"capability_id": "sandbox", "tool_id": "execute", "setting": "ask"},
            {"capability_id": "sandbox", "tool_id": "read_file", "setting": "free"},
        ],
    )
    assert review.grandfathered is False
    assert review.delegates == "ask"
    assert sorted((tool.tool_id, tool.setting) for tool in review.tools) == [
        ("create_issue", "allow"),
        ("create_task", "allow"),
        ("execute", "ask"),
    ]


def test_a_manual_routine_keeps_no_allow() -> None:
    review = _convert(_legacy("restricted"), "manual", consents=[_consent()])
    assert review.tools == ()
    assert review.delegates == "ask"
    assert review.grandfathered is False


def test_a_restricted_review_without_an_action_mode_asked_for_its_effects() -> None:
    review = _convert(_legacy("restricted"), None, consents=[_consent()])
    assert [(tool.tool_id, tool.setting) for tool in review.tools] == [("execute", "allow")]
    assert review.grandfathered is False


def test_a_pending_or_missing_review_stays_what_it_was() -> None:
    pending = {"pending_review": True, "mode": "follow_agent", "unavailable_sources": ["GitHub"]}
    assert MIGRATION._review(pending, "agent", [], []) == {
        "pending_review": True,
        "unavailable_sources": ["GitHub"],
    }
    assert MIGRATION._review(None, None, [], []) is None


@pytest.mark.parametrize("key", [{"tool_id": 3}, {"tool_id": "x"}])
def test_an_unreadable_key_names_no_tool(key: dict[str, Any]) -> None:
    assert MIGRATION._key(key) is None


def test_a_downgrade_returns_each_review_to_the_mode_it_came_from() -> None:
    grandfathered = MIGRATION._review(_legacy("follow_agent"), None, [], [])
    legacy, action_mode = MIGRATION._legacy(grandfathered)
    assert action_mode == "agent"
    assert legacy["mode"] == "follow_agent"
    assert legacy["approved_ceiling"]["mode"] == "follow_agent"
    assert not {"tools", "delegates", "intent_hash", "grandfathered", "platform"} & set(legacy)

    allowed = MIGRATION._review(_legacy("restricted"), "per_tool", [_consent()], [])
    legacy, action_mode = MIGRATION._legacy(allowed)
    # The allow entries are lost: the routine asks again.
    assert action_mode == "per_tool"
    assert legacy["mode"] == "restricted"
    assert legacy["behavior"] is None
    assert "approved_ceiling" not in legacy

    trusting = RoutineSourcePolicy.model_validate(
        MIGRATION._review(_legacy("restricted"), "per_tool", [], [])
    ).model_copy(update={"mode": "trust_agent"})
    stored = trusting.model_dump(mode="json")
    stored["mcp_sources"][CONNECTION]["account"] = "ops@example.com"
    stored["mcp_sources"][CONNECTION]["personal"] = True
    stored["input_connection_id"] = CONNECTION
    stored["input_source"] = {**stored["mcp_sources"][CONNECTION]}
    legacy, action_mode = MIGRATION._legacy(stored)
    assert action_mode == "agent"
    assert "account" not in legacy["mcp_sources"][CONNECTION]
    assert "personal" not in legacy["input_source"]

    pending = {"pending_review": True, "unavailable_sources": []}
    assert MIGRATION._legacy(pending) == ({**pending, "mode": "restricted"}, "agent")
    assert MIGRATION._legacy(None) == (None, "per_tool")
