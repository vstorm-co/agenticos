"""Removing duplicate Tables tools keeps stored agents readable without granting MCP."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.capabilities import all_capabilities
from app.agents.spec import AgentSpec, SpecialistSpec


def test_tables_is_absent_from_the_capability_registry() -> None:
    assert "virtual_tables" not in {item.id for item in all_capabilities()}


def test_old_documents_keep_app_bindings_but_never_add_mcp_authority() -> None:
    table = str(uuid4())
    spec = AgentSpec.model_validate(
        {
            "spec_version": 13,
            "name": "Old agent",
            "capabilities": [
                {
                    "id": "virtual_tables",
                    "config": {
                        "tables": [{"table_id": table, "operations": ["read", "update"]}],
                        "allow_create": True,
                    },
                    "approval": "required",
                    "tool_overrides": {"update_record": {"name": "change_record"}},
                }
            ],
        }
    )
    assert spec.capabilities == []
    assert spec.mcp_servers == []
    assert str(spec.table_bindings[0].table_id) == table
    assert spec.table_bindings[0].operations == ("read", "update")
    assert AgentSpec.from_yaml(spec.to_yaml()) == spec
    assert AgentSpec.model_validate(spec.model_dump()) == spec


def test_explicit_app_bindings_and_restricted_mcp_policy_win() -> None:
    spec = AgentSpec.model_validate(
        {
            "name": "Helper",
            "table_bindings": [],
            "capabilities": [{"id": "virtual_tables", "config": {"allow_create": True}}],
            "mcp_servers": [
                {"account": "platform", "allowed_tools": ["list_agents"], "approval": "all"}
            ],
        }
    )
    assert spec.table_bindings == []
    assert spec.mcp_servers[0].allowed_tools == ["list_agents"]
    assert spec.mcp_servers[0].approval == "all"


def test_disabled_tables_and_inline_specialists_do_not_gain_access() -> None:
    spec = AgentSpec.model_validate(
        {
            "name": "Helper",
            "capabilities": [{"id": "virtual_tables", "enabled": False}],
        }
    )
    assert spec.capabilities == [] and spec.table_bindings == []
    specialist = SpecialistSpec.model_validate(
        {
            "name": "research",
            "description": "Research",
            "instructions": "Read only.",
            "capabilities": [{"id": "virtual_tables"}],
        }
    )
    assert specialist.capabilities == []


def test_invalid_legacy_app_grants_are_reported_as_validation_errors() -> None:
    with pytest.raises(ValidationError):
        AgentSpec.model_validate(
            {
                "name": "Helper",
                "capabilities": [{"id": "virtual_tables", "config": {"tables": "wrong"}}],
            }
        )


def test_empty_app_bindings_do_not_invalidate_old_routine_source_reviews() -> None:
    import hashlib
    import json

    from app.services.routine_sources import _NON_SOURCE_FIELDS, spec_fingerprint

    spec = AgentSpec(name="Old agent", spec_version=13)
    previous = spec.model_dump(mode="json", exclude=set(_NON_SOURCE_FIELDS) | {"table_bindings"})
    expected = hashlib.sha256(
        json.dumps(previous, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert spec_fingerprint(spec) == expected


def test_duplicate_app_table_bindings_are_refused() -> None:
    table = str(uuid4())
    with pytest.raises(ValidationError, match="Bind each table once"):
        AgentSpec.model_validate(
            {
                "name": "Helper",
                "table_bindings": [{"table_id": table}, {"table_id": table}],
            }
        )
