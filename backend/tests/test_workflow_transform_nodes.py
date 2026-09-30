"""The Transform steps: each on an empty list, on items missing a key, and doing its job."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.permissions import AuthContext
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes._transform import MISSING, ItemsInput, assign, lookup, without
from app.workflows.nodes.transform import _handler as steps

pytestmark = pytest.mark.anyio

LEADS = [
    {"name": "Ada", "country": "PL", "score": 90, "tags": ["a", "b"]},
    {"name": "Grace", "country": "DE", "score": 70},
    {"name": "Linus", "score": 90, "tags": [{"tag": "c"}]},
]


def _out(result: Any) -> Any:
    assert isinstance(result, Completed), result
    return result.output.model_dump(mode="json")


def _items(result: Any) -> list[dict[str, Any]]:
    return _out(result)["items"]


def _in(items: list[dict[str, Any]]) -> ItemsInput:
    return ItemsInput(items=items)


class TestTheListContract:
    def test_a_dotted_path_reads_writes_and_removes_nested_fields(self):
        item = {"a": {"b": 1}, "c": 2}
        assert lookup(item, "a.b") == 1
        assert lookup(item, "a.x") is MISSING and lookup(item, "c.d") is MISSING
        assert assign(item, "a.z", 3) == {"a": {"b": 1, "z": 3}, "c": 2}
        assert assign(item, "c.d", 4) == {"a": {"b": 1}, "c": {"d": 4}}
        assert without(item, "a.b") == {"a": {}, "c": 2}
        assert without(item, "x") is item
        assert without(item, "c.d") == item
        assert repr(MISSING) == "MISSING"


class TestEditFields:
    async def test_it_sets_removes_and_keeps_only_what_it_set(self):
        config = steps.EditFieldsConfig.model_validate(
            {
                "set": [
                    {"name": "label", "expression": "join(' ', [item.name, item.country || '?'])"},
                    {"name": "meta.rank", "expression": "index"},
                ],
                "remove": ["tags", "absent"],
            }
        )
        edited = _items(await steps.edit_fields(config, _in(LEADS)))
        assert edited[1] == {
            "name": "Grace",
            "country": "DE",
            "score": 70,
            "label": "Grace DE",
            "meta": {"rank": 1},
        }
        assert edited[2]["label"] == "Linus ?"
        only = steps.EditFieldsConfig.model_validate(
            {"set": [{"name": "who", "expression": "item.missing"}], "only_set": True}
        )
        assert _items(await steps.edit_fields(only, _in(LEADS[:1]))) == [{"who": None}]
        assert _items(await steps.edit_fields(config, None)) == []

    async def test_an_expression_that_fails_names_the_item_and_field(self):
        config = steps.EditFieldsConfig.model_validate(
            {"set": [{"name": "n", "expression": "length(item.score)"}]}
        )
        result = await steps.edit_fields(config, _in(LEADS))
        assert isinstance(result, Failed) and result.error.details == {"index": 0, "field": "n"}
        assert isinstance(await steps.edit_fields(None, None), Failed)


class TestSortAndLimit:
    async def test_it_sorts_by_fields_in_turn_with_missing_keys_last(self):
        config = steps.SortConfig.model_validate(
            {"by": [{"field": "score", "descending": True}, {"field": "country"}]}
        )
        assert [item["name"] for item in _items(await steps.sort(config, _in(LEADS)))] == [
            "Ada",
            "Linus",
            "Grace",
        ]
        by_country = steps.SortConfig.model_validate({"by": [{"field": "country"}]})
        assert [item["name"] for item in _items(await steps.sort(by_country, _in(LEADS)))] == [
            "Grace",
            "Ada",
            "Linus",
        ]
        mixed = [{"v": "b"}, {"v": 2}, {"v": True}, {"v": [1]}, {"v": None}]
        assert [
            item["v"]
            for item in _items(
                await steps.sort(
                    steps.SortConfig.model_validate({"by": [{"field": "v"}]}), _in(mixed)
                )
            )
        ] == [2, "b", True, [1], None]
        assert _items(await steps.sort(config, None)) == []
        assert isinstance(await steps.sort(None, None), Failed)

    async def test_it_keeps_the_first_or_the_last(self):
        first = steps.LimitConfig(count=2)
        last = steps.LimitConfig(count=1, from_end=True)
        assert len(_items(await steps.limit(first, _in(LEADS)))) == 2
        assert _items(await steps.limit(last, _in(LEADS)))[0]["name"] == "Linus"
        assert _items(await steps.limit(first, None)) == []
        assert isinstance(await steps.limit(None, None), Failed)


class TestRemoveDuplicates:
    async def test_it_keeps_the_first_of_each_on_the_fields_named_or_the_whole_item(self):
        by_score = steps.RemoveDuplicatesConfig(fields=("score",))
        assert [
            item["name"] for item in _items(await steps.remove_duplicates(by_score, _in(LEADS)))
        ] == ["Ada", "Grace"]
        by_country = steps.RemoveDuplicatesConfig(fields=("country",))
        missing = [{"n": 1}, {"n": 2}, {"country": None}]
        assert len(_items(await steps.remove_duplicates(by_country, _in(missing)))) == 2
        whole = [{"a": 1, "b": 2}, {"b": 2, "a": 1}, {"a": 2}]
        assert len(_items(await steps.remove_duplicates(None, _in(whole)))) == 2
        assert _items(await steps.remove_duplicates(None, None)) == []


class TestAggregateSplitOutSummarize:
    async def test_aggregate_collects_each_fields_values_leaving_out_the_missing(self):
        config = steps.AggregateConfig(fields=("country", "score"))
        assert _out(await steps.aggregate(config, _in(LEADS))) == {
            "values": {"country": ["PL", "DE"], "score": [90, 70, 90]}
        }
        assert _out(await steps.aggregate(config, None)) == {"values": {"country": [], "score": []}}
        assert isinstance(await steps.aggregate(None, None), Failed)

    async def test_split_out_makes_an_item_of_each_element(self):
        config = steps.SplitOutConfig(field="tags")
        split = _items(await steps.split_out(config, _in(LEADS)))
        assert [item.get("tags", item.get("tag")) for item in split] == ["a", "b", None, "c"]
        assert split[0]["name"] == "Ada" and "tags" in split[0]
        bare = steps.SplitOutConfig(field="tags", keep_other_fields=False)
        assert _items(await steps.split_out(bare, _in(LEADS[:1]))) == [{"tags": "a"}, {"tags": "b"}]
        assert _items(await steps.split_out(config, None)) == []
        assert isinstance(await steps.split_out(None, None), Failed)

    async def test_summarize_groups_and_summarizes_numbers_only(self):
        config = steps.SummarizeConfig.model_validate(
            {
                "group_by": ["score"],
                "summaries": [
                    {"operation": "count"},
                    {"operation": "sum", "field": "score"},
                    {"operation": "average", "field": "score"},
                    {"operation": "min", "field": "name"},
                    {"operation": "max", "field": "score"},
                    {"operation": "count_distinct", "field": "country"},
                ],
            }
        )
        rows = _items(await steps.summarize(config, _in(LEADS)))
        assert rows[0] == {
            "score": 90,
            "count": 2,
            "sum_score": 180,
            "average_score": 90.0,
            "min_name": None,
            "max_score": 90,
            "count_distinct_country": 1,
        }
        ungrouped = steps.SummarizeConfig.model_validate(
            {"summaries": [{"operation": "average", "field": "absent"}]}
        )
        assert _items(await steps.summarize(ungrouped, _in(LEADS))) == [{"average_absent": None}]
        grouped_missing = steps.SummarizeConfig.model_validate(
            {"group_by": ["country"], "summaries": [{"operation": "count"}]}
        )
        assert _items(await steps.summarize(grouped_missing, _in(LEADS)))[2] == {
            "country": None,
            "count": 1,
        }
        assert _items(await steps.summarize(config, None)) == []
        assert isinstance(await steps.summarize(None, None), Failed)
        with pytest.raises(ValidationError, match="needs the field"):
            steps.Summary(operation="sum")


class TestDateTimeAndCrypto:
    async def test_a_moment_is_moved_and_written_out_in_a_timezone(self):
        # As a bound value arrives: JSON text, here with no timezone of its own.
        moment = steps.DateTimeInput.model_validate({"value": "2026-01-15T12:00:00"})
        added = steps.DateTimeConfig(
            operation="add", amount=2, unit="hours", timezone="Europe/Warsaw", format="%H:%M"
        )
        assert _out(await steps.date_time(added, moment))["formatted"] == "15:00"
        subtracted = steps.DateTimeConfig(operation="subtract", amount=1, unit="days", format="%d")
        assert _out(await steps.date_time(subtracted, moment))["formatted"] == "14"
        formatted = steps.DateTimeConfig(operation="format", format="%Y")
        assert _out(await steps.date_time(formatted, moment))["formatted"] == "2026"
        now = _out(await steps.date_time(None, None))
        assert now["value"].startswith(str(datetime.now(UTC).year))
        refused = await steps.date_time(steps.DateTimeConfig(operation="add", amount=1), None)
        assert isinstance(refused, Failed) and refused.error.code == "DATETIME_NEEDS_A_VALUE"
        with pytest.raises(ValidationError, match="is not a timezone"):
            steps.DateTimeConfig(timezone="Mars/Base")

    async def test_a_step_naming_no_timezone_writes_in_the_runs(self):
        moment = steps.DateTimeInput.model_validate({"value": "2026-01-15T12:00:00Z"})
        unnamed = steps.DateTimeConfig(operation="format", format="%H:%M")
        running = context.DispatchContext(
            organization_id=uuid.uuid4(),
            workflow_run_id=uuid.uuid4(),
            node_run_id=uuid.uuid4(),
            node_instance_id=uuid.uuid4(),
            attempt_no=1,
            auth=AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner"),
            resumed_agent_run_id=None,
            timezone="Asia/Tokyo",
        )
        with context.dispatching_as(running):
            assert _out(await steps.date_time(unnamed, moment))["formatted"] == "21:00"
            named = steps.DateTimeConfig(operation="format", format="%H:%M", timezone="UTC")
            assert _out(await steps.date_time(named, moment))["formatted"] == "12:00"
        # Outside a run - nothing to take it from - it is UTC.
        assert _out(await steps.date_time(unnamed, moment))["formatted"] == "12:00"
        # A cleared field arrives as an explicit null, which names no timezone either.
        assert steps.DateTimeConfig.model_validate({"timezone": None}).timezone is None

    async def test_text_is_hashed_or_encoded_and_ids_are_made(self):
        text = steps.CryptoInput(text="hello")
        sha = _out(await steps.crypto(None, text))["value"]
        assert sha.startswith("2cf24dba")
        assert (
            len(_out(await steps.crypto(steps.CryptoConfig(operation="md5"), text))["value"]) == 32
        )
        encoded = _out(await steps.crypto(steps.CryptoConfig(operation="base64_encode"), text))[
            "value"
        ]
        decoded = await steps.crypto(
            steps.CryptoConfig(operation="base64_decode"), steps.CryptoInput(text=encoded)
        )
        assert _out(decoded)["value"] == "hello"
        broken = await steps.crypto(steps.CryptoConfig(operation="base64_decode"), text)
        assert isinstance(broken, Failed) and broken.error.code == "NOT_BASE64"
        assert (
            len(_out(await steps.crypto(steps.CryptoConfig(operation="uuid"), None))["value"]) == 36
        )
        random = await steps.crypto(steps.CryptoConfig(operation="random_hex", length=4), None)
        assert len(_out(random)["value"]) == 8
