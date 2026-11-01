"""Page queries over a workflow's log: a binding that reads lines a workflow's steps wrote.

The second kind of binding, beside a table query (`artifact_bindings`). It follows the same
rules. At publish the workflow (by id or exact name) and the step (by id or label) resolve
to ids, and the ids are stored with the filters, frozen as a view's filters are. The member
behind the run must be able to view the workflow, and so must the page's owner when the
publish changes the binding. On every load the page's owner is checked again, and only
then, after consent, is the log read, through the same service the `GET /workflows/{id}/logs`
routes use, so the filters and limits are theirs.

A log has no columns, so it has nothing to drift: the binding is served while the owner may
view the workflow and the step is still in the live version or the draft, and `unavailable`
with a reason otherwise. It is never served on a public link.
"""

import json
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow
from app.repositories import workflow as workflow_repo
from app.schemas.artifact import (
    LOG_LINES_MAX,
    LogDay,
    WorkflowLogBinding,
    WorkflowLogDisclosure,
    WorkflowLogParts,
    WorkflowLogRequest,
)
from app.schemas.workflow_log_entry import (
    LogFilters,
    WorkflowLogEntryRead,
    is_run_filter,
    is_time_zone,
)
from app.services.access import WORKFLOW, resolve_access
from app.services.workflow_execution import WorkflowExecutionService
from app.workflows import _registry

PUBLIC_LINK = (
    "A page that reads a workflow's log can't have a public link: the log is for members "
    "of the organization, and the link opens to anyone."
)
"""Why a page with a workflow-log binding is refused a public link, and a public page one."""


def public_link_problem(names: list[str]) -> str:
    """The refusal for a page that has, or is given, workflow-log bindings and a public link."""
    return f"Binding {', '.join(names)}: {PUBLIC_LINK}"


@dataclass(frozen=True)
class Gone:
    """Why a stored log binding reads nothing now."""

    reason: Literal["creator_lost_access", "source_changed"]
    changed: str | None = None
    """With `source_changed`: what changed, said as `step`."""


@dataclass(frozen=True)
class LogRead:
    """One log binding as a page load read it: its lines, or its counts per day."""

    mode: Literal["lines", "per_day"]
    records: list[dict[str, Any]]
    sizes: list[int]
    """The size in bytes of each of `records`, as the page receives it."""
    matching: int
    """How many lines the filters match, of which `records` are the newest."""
    days: list[LogDay]
    total: int
    window_days: int | None
    tz: str | None

    @property
    def bytes(self) -> int:
        return sum(self.sizes)


async def resolve_log(
    db: AsyncSession,
    name: str,
    request: WorkflowLogRequest,
    person: AuthContext,
    allowed: Collection[UUID],
) -> tuple[WorkflowLogBinding, Workflow, str | None] | str:
    """A requested log binding with its workflow and step as ids, resolved as `person`.

    The workflow must be one of `allowed` - what the agent's Workflows capability binds -
    as an action's must be; one that is not is told as one that does not exist.

    Returns:
        The binding to store, the workflow it reads and a note for the model when the step
        writes nothing to the log, or a sentence saying what is wrong with the request - an
        unknown, unbound or unviewable workflow is told as one.
    """
    problem = _request_problem(name, request)
    if problem is not None:
        return problem
    workflow = await _find(db, request.workflow, person, allowed)
    if isinstance(workflow, str):
        return f"Binding {name}: {workflow}"
    step: UUID | None = None
    note: str | None = None
    if request.step is not None:
        found = await _step(db, workflow, request.step)
        if isinstance(found, str):
            return f"Binding {name}: {found}"
        step, logs = found
        if not logs:
            note = (
                f"Binding {name}: the step {str(request.step)[:64]!r} of {workflow.name!r} has "
                "no Quick Log, so it will read no lines until the step has one."
            )
    binding = WorkflowLogBinding(
        name=name,
        workflow_id=workflow.id,
        node_instance_id=step,
        outcomes=list(dict.fromkeys(request.outcomes)),
        run=request.run,
        include_test=request.include_test,
        lines=request.lines,
        days=request.days if request.per_day else None,
        tz=(request.tz or "UTC") if request.per_day else None,
    )
    return binding, workflow, note


def _request_problem(name: str, request: WorkflowLogRequest) -> str | None:
    """What is wrong with the shape of a request, before any workflow is looked up."""
    if request.per_day == (request.lines is not None):
        return f"Binding {name}: ask for either `lines` (the newest N) or `per_day`, not both."
    if request.lines is not None and request.lines > LOG_LINES_MAX:
        return (
            f"Binding {name}: `lines` is at most {LOG_LINES_MAX}; this one asks for "
            f"{request.lines}."
        )
    if request.per_day and request.days is None:
        return f"Binding {name}: `per_day` needs `days`: 7, 30 or 90."
    if not request.per_day and (request.days is not None or request.tz is not None):
        return f"Binding {name}: `days` and `tz` belong to `per_day`."
    if request.tz is not None and not is_time_zone(request.tz):
        return f"Binding {name}: `tz` is not an IANA time zone name, such as Europe/Warsaw."
    if request.run is not None and not is_run_filter(request.run):
        return f"Binding {name}: `run` is a run id, or its first 4 or more characters."
    return None


async def _find(
    db: AsyncSession, reference: UUID | str, person: AuthContext, allowed: Collection[UUID]
) -> Workflow | str:
    """The bound workflow a reference names that `person` may view, or why it names none."""
    asked = await _candidates(db, reference, person.organization_id)
    viewable = [
        workflow
        for workflow in asked
        if workflow.id in allowed
        and await resolve_access(db, person, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW)
    ]
    if len(viewable) == 1:
        return viewable[0]
    if viewable:
        return f"Several workflows are named {str(reference)[:64]!r}; give the id."
    return f"Workflow {str(reference)[:64]!r} not found. Take its id from `list_workflows`."


async def _candidates(
    db: AsyncSession, reference: UUID | str, organization_id: UUID
) -> list[Workflow]:
    as_id = reference if isinstance(reference, UUID) else _as_uuid(reference)
    found: list[Workflow] = []
    if as_id is not None:
        by_id = await workflow_repo.get(db, as_id, organization_id=organization_id)
        if by_id is not None:
            found.append(by_id)
    if isinstance(reference, str):
        found += [
            workflow
            for workflow in await workflow_repo.list_by_name(
                db, reference, organization_id=organization_id
            )
            if workflow not in found
        ]
    return found


def _as_uuid(text: str) -> UUID | None:
    try:
        return UUID(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class _Step:
    label: str | None
    """What the builder calls the step; `None` when it is left to the catalog's name."""
    kind: str | None
    """The step's catalog name, such as `Send email`; `None` when the catalog dropped it."""
    quick_log: bool
    """Whether the step writes a line to the log - in the live version or the draft."""


async def _steps(db: AsyncSession, workflow: Workflow) -> dict[UUID, _Step]:
    """The steps of the live version and of the draft, by id."""
    graphs: list[dict[str, Any]] = []
    if workflow.current_version_id is not None:
        version = await workflow_repo.get_version(
            db, workflow.current_version_id, organization_id=workflow.organization_id
        )
        assert version is not None  # `current_version_id` is a version of this workflow
        graphs.append(version.graph)
    if workflow.draft_graph:
        graphs.append(workflow.draft_graph)
    steps: dict[UUID, _Step] = {}
    for graph in graphs:
        for node in graph.get("nodes", []):
            node_id = _as_uuid(str(node.get("id")))
            if node_id is None:
                continue
            before = steps.get(node_id)
            steps[node_id] = _Step(
                label=node.get("label") or (before.label if before else None),
                kind=_kind_name(node),
                quick_log=bool(node.get("quick_log")) or (before.quick_log if before else False),
            )
    return steps


def _kind_name(node: dict[str, Any]) -> str | None:
    try:
        return _registry.get(
            str(node.get("definition_id")), int(node.get("definition_version", 1))
        ).name
    except BadRequestError, ValueError:
        return None


async def _step(
    db: AsyncSession, workflow: Workflow, reference: UUID | str
) -> tuple[UUID, bool] | str:
    """The step a reference names, by id, label or - for a step with no label - the name
    of its kind, and whether it writes to the log; or why it names none."""
    steps = await _steps(db, workflow)
    as_id = reference if isinstance(reference, UUID) else _as_uuid(reference)
    if as_id is not None and as_id in steps:
        return as_id, steps[as_id].quick_log
    matches = [step for step, info in steps.items() if info.label == reference] or [
        step for step, info in steps.items() if info.label is None and info.kind == reference
    ]
    if len(matches) == 1:
        return matches[0], steps[matches[0]].quick_log
    asked = str(reference)[:64]
    if matches:
        return f"Several steps of {workflow.name!r} are called {asked!r}; give the id."
    return f"{workflow.name!r} has no step {asked!r}, by id, label or name."


async def owner_problem(
    db: AsyncSession, owner: AuthContext | None, person: AuthContext, name: str, workflow: Workflow
) -> str | None:
    """Whether the page's owner, whose access its data is read with, may view the workflow.

    Nothing to check when the owner is the person, already held to the same rule.
    """
    if owner is not None and owner.user_id == person.user_id:
        return None
    if owner is None:
        return (
            f"Binding {name}: the page's owner is no longer an active member, and a page's "
            "data is read with its owner's access."
        )
    if await resolve_access(db, owner, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW):
        return None
    return (
        f"Binding {name}: the page's owner can't view {workflow.name!r}, and a page's "
        "data is read with its owner's access."
    )


async def reresolve_log(
    db: AsyncSession,
    binding: WorkflowLogBinding,
    *,
    person: AuthContext,
    owner: AuthContext | None,
    allowed: Collection[UUID],
) -> str | None:
    """Why a restored log binding can't stand, in a sentence; `None` when it can.

    The workflow must still be one of `allowed`, `person` restoring and the page's owner must
    both view it, and the step must still be in it.
    """
    workflow = await workflow_repo.get(
        db, binding.workflow_id, organization_id=person.organization_id
    )
    if (
        workflow is None
        or binding.workflow_id not in allowed
        or not await resolve_access(
            db, person, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
        )
    ):
        return (
            f"Binding {binding.name} reads a workflow you can't view, or that the agent no "
            "longer has bound in its Workflows capability."
        )
    if binding.node_instance_id is not None and binding.node_instance_id not in await _steps(
        db, workflow
    ):
        return f"Binding {binding.name} reads a step {workflow.name!r} no longer has."
    return await owner_problem(db, owner, person, binding.name, workflow)


async def availability(
    db: AsyncSession, owner: AuthContext, binding: WorkflowLogBinding
) -> Workflow | Gone:
    """The workflow as its owner may view it now, or why the binding reads nothing."""
    workflow = await workflow_repo.get(
        db, binding.workflow_id, organization_id=owner.organization_id
    )
    if workflow is None or not await resolve_access(
        db, owner, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
    ):
        return Gone("creator_lost_access")
    if binding.node_instance_id is not None and binding.node_instance_id not in await _steps(
        db, workflow
    ):
        return Gone("source_changed", "step")
    return workflow


def _filters(binding: WorkflowLogBinding) -> LogFilters:
    return LogFilters(
        node_instance_id=binding.node_instance_id,
        outcome=list(binding.outcomes) or None,
        include_test=binding.include_test,
        run=binding.run,
    )


def _shaped(entry: WorkflowLogEntryRead) -> dict[str, Any]:
    """A line as a page reads it, nothing else of the row."""
    return {
        "id": str(entry.id),
        "created_at": entry.created_at.isoformat(),
        "step": entry.step_label,
        "outcome": entry.outcome,
        "status": entry.status,
        "message": entry.message,
        "run_id": str(entry.run_id),
    }


async def read_log(db: AsyncSession, owner: AuthContext, binding: WorkflowLogBinding) -> LogRead:
    """A log binding read as the page's owner, by the service behind the log's routes.

    Raises:
        NotFoundError: The owner can no longer view the workflow (`availability` says so
            first; this is the same check once more, where the data is read).
    """
    service = WorkflowExecutionService(db)
    if binding.lines is not None:
        page = await service.workflow_logs(
            owner,
            binding.workflow_id,
            filters=_filters(binding),
            limit=min(binding.lines, settings.ARTIFACT_DATA_MAX_RECORDS, LOG_LINES_MAX),
        )
        records = [_shaped(entry) for entry in page.items]
        return LogRead(
            "lines",
            records,
            [len(json.dumps(record, separators=(",", ":"))) for record in records],
            page.total,
            [],
            0,
            None,
            None,
        )
    assert binding.days is not None  # a stored binding has lines or days
    tz = binding.tz or "UTC"
    summary = await service.workflow_log_summary(
        owner, binding.workflow_id, filters=_filters(binding), days=binding.days, tz=tz
    )
    days = [LogDay(day=day.day.isoformat(), counts=day.counts) for day in summary.by_day]
    return LogRead("per_day", [], [], 0, days, summary.total, summary.days, ZoneInfo(tz).key)


async def parts_of(
    db: AsyncSession, binding: WorkflowLogBinding, workflow: Workflow
) -> WorkflowLogParts:
    """A log binding as structured parts, its workflow and step named as they are now."""
    step: str | None = None
    if binding.node_instance_id is not None:
        info = (await _steps(db, workflow)).get(binding.node_instance_id)
        step = (info.label or info.kind if info is not None else None) or str(
            binding.node_instance_id
        )
    return WorkflowLogParts(
        workflow=workflow.name,
        step=step,
        outcomes=list(binding.outcomes),
        run=binding.run,
        include_test=binding.include_test,
        mode="lines" if binding.lines is not None else "per_day",
        lines=binding.lines,
        days=binding.days,
        tz=binding.tz,
    )


def disclose_log(parts: WorkflowLogParts) -> WorkflowLogDisclosure:
    """A log query in English words: its workflow, each condition, and what is served."""
    filters = ["test runs included" if parts.include_test else "test runs left out"]
    if parts.step is not None:
        filters.append(f"only the step {parts.step}")
    if parts.outcomes:
        filters.append(f"left by {' or '.join(parts.outcomes)}")
    if parts.run is not None:
        filters.append(f"only the run {parts.run}")
    reads = (
        f"the newest {parts.lines} lines, newest first"
        if parts.mode == "lines"
        else f"the number of lines per day over {parts.days} days, in {parts.tz}"
    )
    return WorkflowLogDisclosure(workflow=parts.workflow, filters=filters, reads=reads)


async def workflow_of(
    db: AsyncSession, reader: AuthContext, binding: WorkflowLogBinding
) -> Workflow | None:
    """The workflow, when `reader` may view it: to put the binding into words."""
    workflow = await workflow_repo.get(
        db, binding.workflow_id, organization_id=reader.organization_id
    )
    if workflow is None or not await resolve_access(
        db, reader, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
    ):
        return None
    return workflow
