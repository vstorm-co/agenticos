"""Switch, Filter a list and Combine lists, as their handlers decide - no database."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes.data_combine._handler import (
    DataCombineConfig,
    DataCombineInput,
)
from app.workflows.nodes.data_combine._handler import handle as combine
from app.workflows.nodes.data_filter._handler import DataFilterConfig, DataFilterInput
from app.workflows.nodes.data_filter._handler import handle as filter_items
from app.workflows.nodes.logic_switch._handler import (
    LogicSwitchConfig,
    LogicSwitchInput,
    ports_for,
    routes,
)
from app.workflows.nodes.logic_switch._handler import handle as switch

pytestmark = pytest.mark.anyio

RULES = LogicSwitchConfig.model_validate(
    {
        "rules": [
            {"name": "poland", "condition": "value.country == 'PL'"},
            {"name": "germany", "condition": "value.country == 'DE'"},
        ]
    }
)


def _output(result: Any) -> dict[str, Any]:
    assert isinstance(result, Completed), result
    return result.output.model_dump(mode="json")


class TestSwitch:
    async def test_the_first_rule_that_holds_takes_the_run_and_otherwise_takes_the_rest(self):
        for country, branch in (("PL", "poland"), ("DE", "germany"), ("FR", "otherwise")):
            result = await switch(RULES, LogicSwitchInput(value={"country": country}))
            assert _output(result)["branch"] == branch
        assert routes({"branch": "poland"}) == {"poland"}
        assert routes(None) == frozenset()

    async def test_its_ports_are_its_rules_in_order_then_otherwise(self):
        assert [port.id for port in ports_for(RULES)] == ["in", "poland", "germany", "otherwise"]
        assert [port.id for port in ports_for(None)] == ["in", "otherwise"]

    async def test_a_rule_that_fails_on_its_data_fails_the_step_naming_it(self):
        failing = LogicSwitchConfig.model_validate(
            {"rules": [{"name": "long", "condition": "length(value) > `3`"}]}
        )
        result = await switch(failing, LogicSwitchInput(value=7))
        assert isinstance(result, Failed) and result.error.details == {"rule": "long"}
        assert isinstance(await switch(None, None), Failed)

    def test_rules_need_names_of_their_own_that_are_not_ports_already(self):
        for rules in (
            [{"name": "a", "condition": "value"}, {"name": "a", "condition": "value"}],
            [{"name": "otherwise", "condition": "value"}],
        ):
            with pytest.raises(ValidationError):
                LogicSwitchConfig.model_validate({"rules": rules})
        with pytest.raises(ValidationError, match="does not parse"):
            LogicSwitchConfig.model_validate({"rules": [{"name": "a", "condition": "value["}]})


class TestFilter:
    async def test_it_keeps_the_items_the_condition_holds_for(self):
        config = DataFilterConfig(condition="item.score > `50`")
        items = [{"score": 90}, {"score": 10}, {"score": 60}]
        assert _output(await filter_items(config, DataFilterInput(items=items))) == {
            "items": [{"score": 90}, {"score": 60}],
            "dropped": 1,
        }
        assert _output(await filter_items(config, None)) == {"items": [], "dropped": 0}

    async def test_a_condition_that_fails_on_an_item_names_it(self):
        config = DataFilterConfig(condition="length(item) > `1`")
        result = await filter_items(config, DataFilterInput(items=["ab", 3]))
        assert isinstance(result, Failed) and result.error.details == {"index": 1}
        assert isinstance(await filter_items(None, None), Failed)


class TestCombine:
    FIRST = [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Grace"}]
    SECOND = [{"id": 2, "score": 90}, {"id": 1, "score": 70}, {"id": 3, "score": 10}]

    async def test_append_puts_the_second_list_after_the_first(self):
        result = await combine(None, DataCombineInput(first=[1], second=[2]))
        assert _output(result) == {"items": [1, 2]}
        assert _output(await combine(None, None)) == {"items": []}

    async def test_by_position_and_by_key_merge_objects_the_second_winning(self):
        by_position = await combine(
            DataCombineConfig(mode="by_position"),
            DataCombineInput(first=self.FIRST, second=self.SECOND),
        )
        assert _output(by_position)["items"] == [
            {"id": 2, "name": "Ada", "score": 90},
            {"id": 1, "name": "Grace", "score": 70},
        ]
        by_key = await combine(
            DataCombineConfig(mode="by_key", key="id"),
            DataCombineInput(first=[*self.FIRST, {"id": 9}], second=[*self.SECOND, {"x": 1}]),
        )
        assert _output(by_key)["items"] == [
            {"id": 1, "name": "Ada", "score": 70},
            {"id": 2, "name": "Grace", "score": 90},
            {"id": 9},
        ]

    async def test_merging_item_by_item_needs_objects_and_a_key(self):
        result = await combine(
            DataCombineConfig(mode="by_position"), DataCombineInput(first=[1], second=[{}])
        )
        assert isinstance(result, Failed) and result.error.code == "COMBINE_NEEDS_OBJECTS"
        with pytest.raises(ValidationError, match="the field to match by"):
            DataCombineConfig(mode="by_key")
