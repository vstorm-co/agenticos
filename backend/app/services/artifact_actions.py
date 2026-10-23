"""The workflows a published page may start (#1976): what a version declares, and the checks.

A page cannot act on its own: it names workflows, and a member viewing it starts one as
themselves. What it may name is part of what its publisher reviewed - the workflows bound
in the publishing agent's Workflows capability - so the declaration is checked here, at
publish and again at restore, against that allowlist and against the person's own right to
run each one. A version stores `[{workflow_id, label}]`; the label is page copy written
by a model, so it is kept as plain text of bounded length and never trusted for anything
that decides what runs.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, NotFoundError, RateLimitError
from app.core.permissions import AuthContext, Perm
from app.db.models.artifact import Artifact, ArtifactVersion
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import WorkflowRun, WorkflowRunTrigger
from app.repositories import member_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.artifact import (
    ActionDisclosure,
    ActionRequest,
    ArtifactAction,
    ArtifactActionField,
    ArtifactActionRun,
    ArtifactActionRunStarted,
    ArtifactActionView,
)
from app.schemas.workflow_run import WorkflowRunRead
from app.services import rate_limit
from app.services.access import WORKFLOW, resolve_access
from app.services.artifact_consent import as_themselves
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import WorkflowRunNotFoundError
from app.workflows.contracts.fields import InputField
from app.workflows.nodes.core_input._handler import TriggerInputConfig
from app.workflows.triggers import BY_HAND, DECLARES_FIELDS

MAX_ACTIONS = 5
"""The most workflows one page version may declare."""
MAX_LABEL = 60

NOT_FOUND = "This action is not available on this page."
"""What every refusal that would otherwise say which part of an action is wrong says."""
AS_THEMSELVES = "Only a member acting as themselves can start a page's action."
MAX_ERROR = 200
"""The longest error message a page is told of a run that failed."""

NO_PERSON = "Only a run acting for a member can declare the workflows a page may start."
LIVE_ACTIONS = (
    "This page starts workflows; only a run acting for a member can change it. "
    "Republishing it unchanged is allowed."
)
"""The refusal a run with no member behind it gets for changing a page that has actions."""
KEPT = "kept"
"""What the publish result says of actions carried from the previous version."""

# Control characters, line and paragraph separators, and Unicode format characters (category
# Cf: bidi overrides and isolates, zero-width characters), which can disguise a label's text.
_HIDDEN = frozenset({"Cc", "Cf", "Zl", "Zp"})


@dataclass(frozen=True)
class ActionsChecked:
    """The outcome of checking a declaration: what to store and say, or what is wrong."""

    actions: list[ArtifactAction] = field(default_factory=list)
    disclosures: list[ActionDisclosure] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def clean_label(label: str | None, fallback: str, limit: int = MAX_LABEL) -> str:
    """Plain text of at most `limit` characters: no control characters, no runs of
    blanks; the workflow's name when nothing is left."""
    text = "".join(" " if unicodedata.category(c) in _HIDDEN else c for c in label or "")
    text = " ".join(text.split())[:limit].strip()
    return text or fallback[:limit]


def stored(actions: Sequence[ArtifactAction]) -> list[dict[str, str]]:
    """Actions as a version column holds them."""
    return [{"workflow_id": str(a.workflow_id), "label": a.label} for a in actions]


def actions_of(rows: Sequence[dict[str, object]]) -> list[ArtifactAction]:
    """A version's `actions` column, validated."""
    return [ArtifactAction.model_validate(row) for row in rows]


async def check_actions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    requested: Sequence[ActionRequest],
    person: AuthContext,
    allowed: Collection[UUID],
) -> ActionsChecked:
    """Resolve and check the workflows a publish asks to declare.

    Each is named by id or exact name and must be one of `allowed` - what the agent's
    Workflows capability binds - in this organization, live, starting from Manual or API,
    and viewable and runnable by `person`. One `person` cannot reach is answered like an
    unbound one, so a refusal never names it.
    """
    if len(requested) > MAX_ACTIONS:
        return ActionsChecked(
            problems=[
                f"A page declares at most {MAX_ACTIONS} actions; this one has {len(requested)}."
            ]
        )
    bound = await _bound(db, organization_id, allowed, person)
    actions: list[ArtifactAction] = []
    disclosures: list[ActionDisclosure] = []
    problems: list[str] = []
    for request in requested:
        found = _find(bound, request.workflow)
        if isinstance(found, str):
            problems.append(found)
            continue
        problem = _problem(found)
        if problem is not None:
            problems.append(problem)
            continue
        if any(a.workflow_id == found.id for a in actions):
            problems.append(f"Workflow {found.name!r} is declared twice.")
            continue
        label = clean_label(request.label, found.name)
        actions.append(ArtifactAction(workflow_id=found.id, label=label))
        disclosures.append(ActionDisclosure(workflow=found.name, label=label))
    return ActionsChecked(
        actions=[] if problems else actions,
        disclosures=[] if problems else disclosures,
        problems=list(dict.fromkeys(problems)),
    )


async def reresolve_actions(
    db: AsyncSession,
    stored_actions: Sequence[ArtifactAction],
    *,
    organization_id: UUID,
    person: AuthContext,
    allowed: Collection[UUID],
) -> list[str]:
    """Why a restored version's actions no longer stand, one sentence each; empty when
    every one is still allowed - bound, live, by hand, and viewable and runnable by `person`."""
    bound = await _bound(db, organization_id, allowed, person)
    problems: list[str] = []
    for action in stored_actions:
        workflow = bound.get(action.workflow_id)
        if workflow is None:
            problems.append(
                f"Action {action.label!r} starts a workflow that the agent no longer has "
                "bound in its Workflows capability, that is gone, or that you may not run."
            )
            continue
        problem = _problem(workflow)
        if problem is not None:
            problems.append(problem)
    return problems


async def _bound(
    db: AsyncSession, organization_id: UUID, allowed: Collection[UUID], person: AuthContext
) -> dict[UUID, Workflow]:
    """The allowlisted workflows that exist in this organization and that `person` may
    both view and run, by id. Others are left out, so they cannot be told from absent ones."""
    found: dict[UUID, Workflow] = {}
    for workflow_id in allowed:
        workflow = await workflow_repo.get(db, workflow_id, organization_id=organization_id)
        if workflow is None:
            continue
        if not (
            await resolve_access(db, person, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW)
            and await resolve_access(
                db, person, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
            )
        ):
            continue
        found[workflow.id] = workflow
    return found


def _find(bound: dict[UUID, Workflow], reference: UUID | str) -> Workflow | str:
    """The bound workflow a reference names, or why it names none."""
    if isinstance(reference, UUID):
        by_id = bound.get(reference)
        if by_id is not None:
            return by_id
    else:
        matches = [w for w in bound.values() if w.name == reference or str(w.id) == reference]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return f"Several workflows are named {reference!r}; pass the id from `list_workflows`."
    return (
        f"Workflow {str(reference)[:64]!r} is not bound in this agent's Workflows capability, "
        "so a page cannot start it. Only the workflows listed by `list_workflows` can be "
        "actions."
    )


def _problem(workflow: Workflow) -> str | None:
    """Why `workflow` cannot be a page action; `None` when it can."""
    if workflow.status == WorkflowStatus.ARCHIVED.value:
        return f"Workflow {workflow.name!r} is archived, so a page cannot start it."
    if workflow.live_trigger is None:
        return f"Workflow {workflow.name!r} has no published version, so a page cannot start it."
    if workflow.live_trigger not in BY_HAND:
        return (
            f"Workflow {workflow.name!r} does not start from a Manual or API trigger, "
            "so a page cannot start it."
        )
    return None


def _fields(graph: dict[str, Any]) -> list[InputField]:
    """The fields a version's entry declares, as its run dialog asks for them."""
    entry = next(
        (node for node in graph.get("nodes", []) if node.get("id") == graph.get("entry_node_id")),
        None,
    )
    if entry is None or entry.get("definition_id") not in DECLARES_FIELDS:
        return []
    config = TriggerInputConfig.model_validate(
        {"fields": (entry.get("config") or {}).get("fields", [])}
    )
    return list(config.fields)


async def _runnable(db: AsyncSession, ctx: AuthContext, workflow_id: UUID) -> Workflow | None:
    """The workflow, when `ctx` may view and run it now and it can still start by hand."""
    workflow = await workflow_repo.get(db, workflow_id, organization_id=ctx.organization_id)
    if workflow is None or _problem(workflow) is not None:
        return None
    if not (
        await resolve_access(db, ctx, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW)
        and await resolve_access(db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW)
    ):
        return None
    return workflow


async def viewer_actions(
    db: AsyncSession, ctx: AuthContext, version: ArtifactVersion
) -> list[ArtifactActionView]:
    """The actions `version` declares that `ctx` may run now. One they may not - gone,
    archived, no longer started by hand, or beyond their access - is left out, not named."""
    shown: list[ArtifactActionView] = []
    for action in actions_of(version.actions):
        workflow = await _runnable(db, ctx, action.workflow_id)
        if workflow is None or workflow.current_version_id is None:
            continue
        current = await workflow_repo.get_version(
            db, workflow.current_version_id, organization_id=ctx.organization_id
        )
        shown.append(
            ArtifactActionView(
                workflow_id=workflow.id,
                name=workflow.name,
                label=action.label,
                fields=[
                    ArtifactActionField.model_validate(f.model_dump())
                    for f in _fields(current.graph if current is not None else {})
                ],
            )
        )
    return shown


async def start_action(
    db: AsyncSession,
    ctx: AuthContext,
    artifact: Artifact,
    version: ArtifactVersion,
    workflow_id: UUID,
    run_input: dict[str, Any],
) -> ArtifactActionRunStarted:
    """Start the workflow `version` declares, as `ctx`, from the page `artifact`.

    The caller has decided `version` is the one `ctx` is served. The run is `ctx`'s own:
    their access, their budget, their principal - the page confers nothing.

    Raises:
        AuthorizationError: Not a member acting as themselves.
        NotFoundError: `version` does not declare the workflow, or `ctx` may not run it
            now; the two are told alike.
        RateLimitError: `ctx` started too many runs from this page in the last minute.
    """
    if (
        not as_themselves(ctx)
        or ctx.user_id is None
        or await member_repo.get_active(
            db, organization_id=ctx.organization_id, user_id=ctx.user_id
        )
        is None
    ):
        raise AuthorizationError(message=AS_THEMSELVES, details={"artifact_id": str(artifact.id)})
    if all(a.workflow_id != workflow_id for a in actions_of(version.actions)):
        raise NotFoundError(message=NOT_FOUND, details={"artifact_id": str(artifact.id)})
    if await _runnable(db, ctx, workflow_id) is None:
        raise NotFoundError(message=NOT_FOUND, details={"artifact_id": str(artifact.id)})
    decision = await rate_limit.consume_with_local_floor(
        surface="artifact_action",
        caller=f"org:{ctx.organization_id}:user:{ctx.subject_id}:artifact:{artifact.id}",
        limit=rate_limit.artifact_action_limit(),
    )
    if not decision.allowed:
        raise RateLimitError(
            message="This page started too many runs in the last minute. Wait and try again.",
            details={"retry_after_seconds": decision.retry_after_seconds},
        )
    run = await WorkflowExecutionService(db).start(
        ctx,
        workflow_id,
        triggered_by=WorkflowRunTrigger.APP,
        run_input=run_input,
        source_artifact_id=artifact.id,
        source_version_number=version.number,
    )
    # The input is the person's and can be anything: the trail names the run, which holds it.
    await record_audit(
        db,
        actor_user_id=ctx.subject_id,
        organization_id=ctx.organization_id,
        action="artifact.action_started",
        target_type="artifact",
        target_id=str(artifact.id),
        details={
            "artifact_id": str(artifact.id),
            "version": version.number,
            "workflow_id": str(workflow_id),
            "run_id": str(run.id),
        },
    )
    return ArtifactActionRunStarted(run_id=run.id, status=run.status.value)


def _short(message: object) -> str | None:
    """The first line of an error's message as plain text of at most :data:`MAX_ERROR`
    characters, so a trace or a long dump behind it never reaches a page."""
    if not isinstance(message, str):
        return None
    lines = [line for line in message.splitlines() if line.strip()]
    return clean_label(lines[0] if lines else None, "", MAX_ERROR) or None


def _without_files(value: Any) -> Any:
    """`value` with every file reference removed, wherever it sits in the JSON."""
    if isinstance(value, dict):
        return {
            key: _without_files(item)
            for key, item in value.items()
            if not (isinstance(item, dict) and item.get("kind") == "file")
        }
    if isinstance(value, list):
        return [
            _without_files(item)
            for item in value
            if not (isinstance(item, dict) and item.get("kind") == "file")
        ]
    return value


async def run_state(
    db: AsyncSession, ctx: AuthContext, artifact: Artifact, run_id: UUID
) -> ArtifactActionRun:
    """How a run this page started for `ctx` stands, for the page to read.

    Only its status, answer text and structured answer, with file references taken out,
    and the first line of its error; the rest is on the run's own page.

    Raises:
        NotFoundError: No such run, one another page started, one that is not `ctx`'s, or
            one whose workflow `ctx` may no longer view - all told alike.
    """
    row = await workflow_run_repo.get_run(db, run_id, organization_id=ctx.organization_id)
    if (
        row is None
        or row.source_artifact_id != artifact.id
        or ctx.user_id is None
        or row.execution_principal_user_id != ctx.user_id
    ):
        raise NotFoundError(message="Run not found", details={"run_id": str(run_id)})
    run = await _read(db, ctx, row)
    output = run.output or {}
    finished = run.status.is_terminal
    paused = run.status.value in _PAUSED
    structured = output.get("structured")
    return ArtifactActionRun(
        status=run.status.value,
        finished=finished,
        paused=paused,
        run_path=(
            f"/workflows/{run.workflow_id}/runs/{run.id}?org={ctx.organization_id}"
            if paused
            else None
        ),
        output_text=output.get("text") if isinstance(output.get("text"), str) else None,
        output_structured=(
            _without_files(structured)
            if isinstance(structured, dict) and structured.get("kind") != "file"
            else None
        ),
        error_message=_short((run.error or {}).get("message")),
    )


async def _read(db: AsyncSession, ctx: AuthContext, row: WorkflowRun) -> WorkflowRunRead:
    """The run as the workflows module reads it, which also asks that `ctx` may view its
    workflow; a refusal there reads as a missing run."""
    try:
        return await WorkflowExecutionService(db).get(ctx, row.id)
    except WorkflowRunNotFoundError as exc:
        raise NotFoundError(message="Run not found", details={"run_id": str(row.id)}) from exc


_PAUSED = frozenset({"waiting_approval", "needs_attention"})
