"""Which fields of a spec the assistant may change, and when a change still fits the draft."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.agents.spec import AgentSpec
from app.services import authoring_fields as fields

# Fixed, because they name parametrized cases: xdist workers must collect the same ids.
COLLECTION = "6f1c0a52-3d0e-4c51-9a41-0b6f4f3c2a10"
CONNECTION = "0b8e5d7a-91c4-4e0b-8f2e-5a3c6d1e9b20"
MODEL = "3a9d2c4e-7b15-4f8a-a6c2-1e0d9b8f7c30"
OTHER_MODEL = "c4e17b20-5d3a-4b9e-8c61-2f0a7d6e5b40"


def _spec(**values: Any) -> AgentSpec:
    return AgentSpec.model_validate(
        {
            "name": "Clerk",
            "instructions": "Answer refunds.",
            "description": "Refund questions",
            "model_profile_id": MODEL,
            "model_settings": {"temperature": 0.7},
            "max_steps": 10,
            "capabilities": [
                {"id": "knowledge", "config": {"default_top_k": 5}},
                {"id": "sandbox", "approval": "never"},
                {
                    "id": "subagents",
                    "config": {
                        "inline": [
                            {"name": "triage", "description": "Sorts", "instructions": "Sort."}
                        ]
                    },
                },
            ],
            "collection_ids": [COLLECTION],
            "mcp_servers": [
                {"account": "organization", "connection_id": CONNECTION},
                {"account": "personal", "catalog_key": "notion", "allowed_tools": ["search"]},
            ],
            **values,
        }
    )


class TestTargets:
    def test_every_target_parses_and_nothing_else_does(self):
        for path in (
            "description",
            "model_profile_id",
            "model_settings/top_p",
            "max_steps",
            "capabilities",
            "capabilities/knowledge/config",
            "capabilities/sandbox/approval",
            "capabilities/sandbox/tool_approval/execute",
            "capabilities/subagents/inline/triage/description",
            "collection_ids",
            "context_ids",
            f"mcp_servers/{CONNECTION}/allowed_tools",
        ):
            address = fields.parse(path)
            assert address is not None, path
            assert fields.ops(address)
        for path in (
            "budget/monthly_usd",
            "observability",
            "model_settings/seed",
            "capabilities/knowledge",
            "capabilities/knowledge/secret_id",
            "capabilities/subagents/inline/triage/instructions",
            "capabilities/subagents/config",
            "subagents",
            "mcp_servers/x",
        ):
            assert fields.parse(path) is None, path

    def test_a_personal_binding_is_named_by_its_account_and_catalog_key(self):
        assert fields.server_key({"account": "personal", "catalog_key": "notion"}) == (
            "personal:notion"
        )
        assert fields.server_key({"account": "platform"}) == "platform:"


class TestSet:
    @pytest.mark.parametrize(
        ("path", "base", "new", "check"),
        [
            ("description", "Refund questions", "Refunds and returns", "description"),
            ("model_profile_id", MODEL, OTHER_MODEL, "model_profile_id"),
            ("model_settings/temperature", 0.7, 0.2, "temperature"),
            ("max_steps", 10, 20, "max_steps"),
            ("capabilities/knowledge/config", {"default_top_k": 5}, {"default_top_k": 8}, None),
            ("capabilities/sandbox/approval", "never", "required", None),
            ("capabilities/sandbox/tool_approval/execute", None, "required", None),
            ("capabilities/subagents/inline/triage/description", "Sorts", "Sorts tickets", None),
            (f"mcp_servers/{CONNECTION}/allowed_tools", None, ["search"], None),
            ("mcp_servers/personal:notion/allowed_tools", ["search"], None, None),
        ],
    )
    def test_a_change_applies_once_and_undoes_while_it_stands(self, path, base, new, check):
        spec = _spec()
        document = spec.model_dump(mode="json")
        address = fields.parse(path)
        assert address is not None
        assert fields.read(document, address) == base
        assert fields.stage(spec, path, "set", new) == (base, new)

        written = fields.apply(spec, path, "set", base, new)

        assert written is not None
        assert fields.read(written.model_dump(mode="json"), address) == new
        if check == "temperature":
            assert written.model_settings.temperature == new
        assert fields.apply(written, path, "set", base, new) is None
        assert fields.undo(written, path, "set", base, new) == spec

    def test_a_value_edited_since_is_neither_written_over_nor_undone(self):
        spec = _spec()
        edited = _spec(max_steps=30)

        assert fields.apply(edited, "max_steps", "set", 10, 20) is None
        written = fields.apply(spec, "max_steps", "set", 10, 20)
        assert written is not None
        assert fields.undo(edited, "max_steps", "set", 10, 20) is None

    def test_a_path_that_no_longer_resolves_is_stale(self):
        spec = _spec(capabilities=[], mcp_servers=[])
        for path in (
            "capabilities/knowledge/config",
            "capabilities/subagents/inline/triage/description",
            f"mcp_servers/{CONNECTION}/allowed_tools",
        ):
            address = fields.parse(path)
            assert address is not None
            assert fields.read(spec.model_dump(mode="json"), address) is fields.MISSING
            assert fields.apply(spec, path, "set", None, "x") is None
            assert fields.stage(spec, path, "set", "x") == "does_not_apply"

    def test_a_value_the_spec_refuses_does_not_apply(self):
        assert fields.apply(_spec(), "model_settings/temperature", "set", 0.7, 5) is None

    def test_an_unknown_path_neither_applies_nor_undoes(self):
        assert fields.apply(_spec(), "budget", "set", None, 1) is None
        assert fields.undo(_spec(), "budget", "set", None, 1) is None

    def test_a_tool_approval_set_back_to_none_is_removed(self):
        spec = _spec()
        path = "capabilities/sandbox/tool_approval/execute"
        written = fields.apply(spec, path, "set", None, "required")
        assert written is not None
        assert fields.undo(written, path, "set", None, "required") == spec


class TestLists:
    def test_an_item_is_added_once_and_removed_by_undo(self):
        spec = _spec()
        other = str(uuid.uuid4())

        written = fields.apply(spec, "context_ids", "add", None, other)

        assert written is not None and str(written.context_ids[-1]) == other
        assert fields.apply(written, "context_ids", "add", None, other) is None
        assert fields.undo(written, "context_ids", "add", None, other) == spec
        assert fields.undo(spec, "context_ids", "add", None, other) is None

    def test_an_item_is_removed_once_and_put_back_by_undo(self):
        spec = _spec()

        staged = fields.stage(spec, "collection_ids", "remove", COLLECTION)
        assert isinstance(staged, tuple)
        base, new = staged
        written = fields.apply(spec, "collection_ids", "remove", base, new)

        assert (base, new) == (COLLECTION, None)
        assert written is not None and written.collection_ids == []
        assert fields.apply(written, "collection_ids", "remove", base, new) is None
        restored = fields.undo(written, "collection_ids", "remove", base, new)
        assert restored is not None and [str(item) for item in restored.collection_ids] == [
            COLLECTION
        ]
        assert fields.undo(spec, "collection_ids", "remove", base, new) is None

    def test_a_capability_is_removed_whole_and_only_as_it_was_read(self):
        spec = _spec()
        staged = fields.stage(spec, "capabilities", "remove", "knowledge")
        assert isinstance(staged, tuple)
        base = staged[0]
        edited = _spec(capabilities=[{"id": "knowledge", "config": {"default_top_k": 9}}])

        assert base == spec.model_dump(mode="json")["capabilities"][0]
        assert fields.apply(edited, "capabilities", "remove", base, None) is None
        written = fields.apply(spec, "capabilities", "remove", base, None)
        assert written is not None and "knowledge" not in [c.id for c in written.capabilities]
        assert fields.stage(spec, "capabilities", "remove", "absent") == "does_not_apply"

    def test_an_added_capability_arrives_with_its_writing_tools_gated(self):
        spec = _spec(capabilities=[])

        staged = fields.stage(spec, "capabilities", "add", {"id": "sandbox"})
        assert isinstance(staged, tuple)
        binding = staged[1]

        assert binding["tool_approval"] == {
            "write_file": "required",
            "edit_file": "required",
            "execute": "required",
        }
        assert fields.gated({"id": "sandbox", "approval": "required"}) == {
            "id": "sandbox",
            "approval": "required",
        }
        assert fields.gated({"id": "charts"}) == {"id": "charts"}
        assert fields.writing_tools("retired") == []
        written = fields.apply(spec, "capabilities", "add", None, binding)
        assert written is not None
        assert fields.undo(written, "capabilities", "add", None, binding) == spec

    def test_an_added_collection_id_is_stored_as_text(self):
        added = uuid.uuid4()
        assert fields.stage(_spec(), "collection_ids", "add", added) == (None, str(added))


def test_a_safeguard_may_be_added():
    base, new = fields.stage(_spec(), "capabilities", "add", {"id": "guardrails", "config": {}})
    assert base is None and new["id"] == "guardrails"


def test_a_change_never_accepted_says_why_whatever_the_draft_holds():
    assert fields.standing_refusal("capabilities/subagents/config", "set", {}, {}) == (
        "not_a_target"
    )
    assert (
        fields.standing_refusal("capabilities", "add", None, {"id": "subagents"}) == "not_a_target"
    )
    assert (
        fields.standing_refusal("capabilities", "remove", {"id": "guardrails"}, None)
        == "weakens_protection"
    )
    assert fields.standing_refusal("capabilities", "add", None, {"id": "charts"}) is None
    assert fields.standing_refusal("capabilities", "add", None, "subagents") is None
    assert fields.standing_refusal("capabilities", "remove", {"id": "subagents"}, None) is None


def test_only_a_removed_or_reconfigured_safeguard_weakens_protection():
    assert fields.weakens_protection("capabilities", "remove", {"id": "guardrails"})
    assert fields.weakens_protection("capabilities/guardrails/config", "set", {})
    assert not fields.weakens_protection("capabilities", "remove", {"id": "charts"})
    assert not fields.weakens_protection("capabilities", "remove", "guardrails")
    assert not fields.weakens_protection("capabilities/knowledge/config", "set", {})
    assert not fields.weakens_protection("capabilities/guardrails/approval", "set", "never")
    assert not fields.weakens_protection("budget", "set", 5)


class TestRefusals:
    @pytest.mark.parametrize(
        ("spec_values", "path", "op", "value", "reason"),
        [
            ({}, "budget", "set", 5, "not_a_target"),
            ({}, "collection_ids", "set", [], "operation"),
            ({}, "capabilities/sandbox/approval", "set", "never", "loosens_approval"),
            ({}, "capabilities/knowledge/approval", "set", "never", "loosens_approval"),
            ({}, "capabilities/knowledge/approval", "set", "sometimes", "loosens_approval"),
            ({}, "capabilities/sandbox/tool_approval/execute", "set", "never", "loosens_approval"),
            ({}, "capabilities", "add", {"id": "retired"}, "unknown_capability"),
            ({}, "capabilities", "add", "knowledge", "unknown_capability"),
            (
                {},
                "capabilities",
                "add",
                {"id": "clock", "config": {"timezone": 5}},
                "invalid_config",
            ),
            ({}, "capabilities", "add", {"id": "clock", "approval": "often"}, "invalid_config"),
            (
                {},
                "capabilities/knowledge/config",
                "set",
                {"default_top_k": "many"},
                "invalid_config",
            ),
            ({}, "capabilities", "add", {"id": "knowledge"}, "does_not_apply"),
            ({}, "model_settings/temperature", "set", 5, "does_not_apply"),
            ({}, "collection_ids", "remove", OTHER_MODEL, "does_not_apply"),
            (
                {"capabilities": [{"id": "guardrails", "config": {}}]},
                "capabilities",
                "remove",
                {"id": "guardrails"},
                "weakens_protection",
            ),
            ({}, "capabilities/subagents/config", "set", {"inline": []}, "not_a_target"),
            ({}, "capabilities", "add", {"id": "subagents", "config": {}}, "not_a_target"),
            (
                {"capabilities": [{"id": "guardrails", "config": {}}]},
                "capabilities/guardrails/config",
                "set",
                {},
                "weakens_protection",
            ),
        ],
    )
    def test_what_cannot_be_staged_says_why(self, spec_values, path, op, value, reason):
        assert fields.stage(_spec(**spec_values), path, op, value) == reason

    def test_a_config_for_a_capability_without_a_schema_is_not_checked(self):
        spec = _spec(capabilities=[{"id": "charts"}])
        assert fields.stage(spec, "capabilities/charts/config", "set", {"anything": 1}) == (
            {},
            {"anything": 1},
        )

    def test_a_config_for_a_retired_capability_is_not_checked_against_a_schema(self):
        spec = _spec(capabilities=[{"id": "retired"}])
        assert fields.stage(spec, "capabilities/retired/config", "set", {"x": 1}) == ({}, {"x": 1})
