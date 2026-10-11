"""The table read steps' refusals and branch choice, unit by unit.

`tests/integration/test_workflow_table_nodes.py` runs them in graphs against a
real Postgres; what is left here is what a graph can only reach by bypassing
validation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.workflows.contracts.results import Failed
from app.workflows.nodes.table_describe._handler import check_resources as describe_check
from app.workflows.nodes.table_describe._handler import handle as describe
from app.workflows.nodes.table_exists._handler import handle as table_exists
from app.workflows.nodes.table_exists._handler import routes as table_routes
from app.workflows.nodes.table_record_exists._handler import check_resources as record_check
from app.workflows.nodes.table_record_exists._handler import handle as record_exists
from app.workflows.nodes.table_record_exists._handler import routes as record_routes

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("handle", [describe, table_exists, record_exists])
async def test_a_step_with_nothing_to_look_up_says_so(handle):
    result = await handle(None, None)
    assert isinstance(result, Failed) and result.error.code == "TABLE_STEP_NOT_CONFIGURED"


@pytest.mark.parametrize("routes", [table_routes, record_routes])
def test_the_branch_is_yes_no_or_none_without_an_output(routes):
    assert routes({"exists": True}) == {"yes"}
    assert routes({"exists": False}) == {"no"}
    assert routes(None) == frozenset()


@pytest.mark.parametrize("check", [describe_check, record_check])
async def test_a_config_of_another_step_is_not_this_checks_to_judge(check):
    assert await check(MagicMock(), MagicMock(), MagicMock()) == []
