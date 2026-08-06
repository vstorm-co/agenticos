"""What run history tells a surface about a delegated run.

`AgentRunRead` is serialised from the ORM row by `response_model`, so a field the
schema does not declare is a field the API silently drops - no error, no warning,
just a client that cannot see it. That is the failure this file exists for: the
migration that added `parent_run_id` describes the child row as "the run history
entry a delegation panel links to", and for a while the column existed, the row
was written, and the API sent neither the link nor the task id. Nothing was
broken enough to notice.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.schemas.agent_run import AgentRunRead


def _row(**overrides: object) -> AgentRun:
    """A finished run row, not persisted - this is about serialisation only."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "surface": RunSurface.WEB.value,
        "status": RunStatus.COMPLETED.value,
        "input_tokens": 56,
        "output_tokens": 5,
        "cost_usd": Decimal("0.000030"),
        "cost_is_partial": False,
    }
    return AgentRun(**{**defaults, **overrides})


def test_a_delegated_run_reports_the_run_it_was_delegated_from() -> None:
    """The link reaches the client, which is the whole point of storing it.

    Without it nothing outside the database can tell a delegated run from one a
    person started, and the two must not be read the same way: a parent's cost
    already contains its children's, so a surface summing a page of rows
    double-counts every delegation.
    """
    parent_id = uuid.uuid4()
    read = AgentRunRead.model_validate(_row(parent_run_id=parent_id, subagent_task_id="9abbab49"))

    assert read.parent_run_id == parent_id
    assert read.subagent_task_id == "9abbab49"


def test_a_run_somebody_started_reports_no_parent() -> None:
    """Null rather than absent, so a client branches on one shape.

    `parent_run_id IS NOT NULL` is the question people actually ask of this
    table - there is deliberately no `subagent` surface - so the negative case
    has to be expressible rather than inferred from a missing key.
    """
    read = AgentRunRead.model_validate(_row())

    assert read.parent_run_id is None
    assert read.subagent_task_id is None


def test_an_orphaned_delegation_reports_no_task_id() -> None:
    """Deleting the parent must not leave a handle pointing at nothing.

    The foreign key is `ON DELETE SET NULL` and can only null its own column,
    so the stored row keeps `subagent_task_id` and becomes a top-level run
    carrying a delegation handle whose transcript went with the parent. Every
    surface reads this schema, so the handle is withheld here once rather than
    guarded by each reader - or by a trigger on the hottest insert table.
    """
    read = AgentRunRead.model_validate(_row(parent_run_id=None, subagent_task_id="9abbab49"))

    assert read.parent_run_id is None
    assert read.subagent_task_id is None
