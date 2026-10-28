"""`WorkflowLogAlertService` - alert people when a workflow's log crosses a threshold.

A rule counts the real-run lines a workflow's Quick Logs wrote in a window and tells its
audience when enough of them match. Reading the rules needs `workflows:view` on the
workflow and changing them needs `workflows:edit`, resolved on that workflow like its
evals and exposures; a refusal reads as "not found". A per-minute job evaluates every
enabled rule (`evaluate`), each in a transaction of its own.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow
from app.db.models.workflow_log_alert import WorkflowLogAlertFiring, WorkflowLogAlertRule
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_log_alert as alert_repo
from app.repositories import workflow_log_entry as log_repo
from app.schemas.workflow_log_alert import (
    MAX_RULES_PER_WORKFLOW,
    LogAlertAudience,
    WorkflowLogAlertCreate,
    WorkflowLogAlertFiringRead,
    WorkflowLogAlertList,
    WorkflowLogAlertRead,
    WorkflowLogAlertUpdate,
)
from app.services.access import WORKFLOW, resolve_access
from app.services.notifications import NotificationService
from app.workflows import _registry
from app.workflows.contracts.policy import ERROR_PORT
from app.workflows.graph.model import WorkflowGraph
from app.workflows.graph.validate import instance_ports

logger = logging.getLogger(__name__)


class WorkflowLogAlertService:
    """Write a workflow's log alert rules, and evaluate them."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_rules(self, ctx: AuthContext, workflow_id: UUID) -> WorkflowLogAlertList:
        """The workflow's rules, oldest first, each with its last alert.

        Raises:
            NotFoundError: No such workflow, or this caller may not view it.
        """
        workflow = await self._workflow(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        rules = await alert_repo.list_for_workflow(
            self.db, organization_id=ctx.organization_id, workflow_id=workflow.id
        )
        firings = await alert_repo.latest_firings(self.db, [rule.id for rule in rules])
        return WorkflowLogAlertList(items=[_read(rule, firings.get(rule.id)) for rule in rules])

    async def create_rule(
        self, ctx: AuthContext, workflow_id: UUID, data: WorkflowLogAlertCreate
    ) -> WorkflowLogAlertRead:
        """A new rule, checked against the steps of the workflow that log.

        The workflow row is locked so two creators cannot both pass the cap.

        Raises:
            NotFoundError: As `list_rules`, for a caller who may not edit the workflow.
            BadRequestError: The rule names a step or an outcome the workflow's Quick Logs
                do not write, names `chosen` with no members (or members without `chosen`),
                or the workflow already holds `MAX_RULES_PER_WORKFLOW` rules.
        """
        workflow = await self._workflow(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        if (
            await alert_repo.count_for_workflow(
                self.db, organization_id=ctx.organization_id, workflow_id=workflow.id
            )
            >= MAX_RULES_PER_WORKFLOW
        ):
            raise BadRequestError(
                message=f"A workflow holds at most {MAX_RULES_PER_WORKFLOW} log alert rules",
                details={"workflow_id": str(workflow.id)},
            )
        audience = [a.value for a in data.audience]
        _check_audience(audience, data.user_ids)
        await self._check_steps(workflow, data.node_instance_id, data.outcomes)
        rule = await alert_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            name=data.name,
            outcomes=data.outcomes,
            node_instance_id=data.node_instance_id,
            message_contains=data.message_contains,
            threshold=data.threshold,
            window_minutes=data.window_minutes,
            audience=audience,
            user_ids=data.user_ids,
            enabled=data.enabled,
            created_by_user_id=ctx.subject_id,
        )
        await self._audit(ctx, workflow, "workflow.log_alert_created", rule)
        return _read(rule, None)

    async def update_rule(
        self, ctx: AuthContext, workflow_id: UUID, rule_id: UUID, data: WorkflowLogAlertUpdate
    ) -> WorkflowLogAlertRead:
        """Change the fields sent; the rest of the rule stands.

        A step or outcome is checked against the workflow only when this change names one,
        so switching a rule off still works after its step was removed. A rule whose
        window or threshold changed is judged afresh; its last alert holds off the next one
        for the new window.

        Raises:
            NotFoundError: The workflow or the rule is out of reach.
            BadRequestError: As `create_rule`.
        """
        workflow = await self._workflow(ctx, workflow_id, Perm.WORKFLOWS_EDIT)
        rule = await self._rule(ctx, workflow, rule_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "audience" in fields:
            fields["audience"] = [a.value for a in data.audience or []]
        if "audience" in fields or "user_ids" in fields:
            _check_audience(
                fields.get("audience", rule.audience), fields.get("user_ids", rule.user_ids)
            )
        if "node_instance_id" in fields or "outcomes" in fields:
            await self._check_steps(
                workflow,
                fields.get("node_instance_id", rule.node_instance_id),
                fields.get("outcomes", rule.outcomes),
            )
        rule = await alert_repo.update(self.db, rule=rule, fields=fields)
        firings = await alert_repo.latest_firings(self.db, [rule.id])
        await self._audit(ctx, workflow, "workflow.log_alert_updated", rule, fields=sorted(fields))
        return _read(rule, firings.get(rule.id))

    async def delete_rule(self, ctx: AuthContext, workflow_id: UUID, rule_id: UUID) -> None:
        """Remove a rule and its history.

        Raises:
            NotFoundError: The workflow or the rule is out of reach.
        """
        workflow = await self._workflow(ctx, workflow_id, Perm.WORKFLOWS_EDIT)
        rule = await self._rule(ctx, workflow, rule_id)
        await alert_repo.delete(self.db, rule)
        await self._audit(ctx, workflow, "workflow.log_alert_deleted", rule)

    async def due_rule_ids(self, *, now: datetime) -> list[UUID]:
        """Every enabled rule in every organization that has not fired within its window as of
        `now`, for the evaluator to walk; a rule in its hold-off costs nothing."""
        return await alert_repo.list_due_ids(self.db, now=now)

    async def evaluate(self, rule_id: UUID, *, now: datetime) -> bool:
        """Count the rule's matching lines in the window ending `now`, and alert when enough.

        The rule row is locked first, so overlapping evaluations of one rule take turns and
        the second finds `last_fired_at` already set: a rule alerts at most once per window.
        The firing, the new `last_fired_at` and the notification rows commit together or
        not at all, so a failed write is simply tried again on the next tick.

        Returns:
            Whether the rule fired.
        """
        rule = await alert_repo.get_for_update(self.db, rule_id)
        if rule is None or not rule.enabled:
            return False
        window = timedelta(minutes=rule.window_minutes)
        if rule.last_fired_at is not None and rule.last_fired_at > now - window:
            return False
        window_start = now - window
        count = await log_repo.count_matching(
            self.db,
            organization_id=rule.organization_id,
            workflow_id=rule.workflow_id,
            outcomes=list(rule.outcomes),
            node_instance_id=rule.node_instance_id,
            message_contains=rule.message_contains,
            since=window_start,
            until=now,
            after=rule.last_fired_at,
        )
        if count < rule.threshold:
            return False
        workflow = await workflow_repo.get(
            self.db, rule.workflow_id, organization_id=rule.organization_id
        )
        assert workflow is not None  # the rule cascades with its workflow
        firing = await alert_repo.create_firing(
            self.db, rule_id=rule.id, fired_at=now, count=count, window_start=window_start
        )
        await alert_repo.update(self.db, rule=rule, fields={"last_fired_at": now})
        await NotificationService(self.db).workflow_log_alert(
            rule, workflow, firing_id=firing.id, count=count
        )
        return True

    async def _workflow(
        self, ctx: AuthContext, workflow_id: UUID, perm: Perm, *, lock: bool = False
    ) -> Workflow:
        read = workflow_repo.get_for_update if lock else workflow_repo.get
        workflow = await read(self.db, workflow_id, organization_id=ctx.organization_id)
        if workflow is None or not await resolve_access(
            self.db, ctx, workflow, perm, resource_type=WORKFLOW
        ):
            raise NotFoundError(message="Workflow not found", details={"workflow_id": workflow_id})
        return workflow

    async def _rule(
        self, ctx: AuthContext, workflow: Workflow, rule_id: UUID
    ) -> WorkflowLogAlertRule:
        rule = await alert_repo.get(
            self.db, rule_id, organization_id=ctx.organization_id, workflow_id=workflow.id
        )
        if rule is None:
            raise NotFoundError(
                message="Log alert rule not found", details={"rule_id": str(rule_id)}
            )
        return rule

    async def _check_steps(
        self, workflow: Workflow, node_instance_id: UUID | None, outcomes: list[str]
    ) -> None:
        """Refuse a step that does not log, and outcomes the step (or any step that logs,
        when none is named) never leaves by."""
        steps = await self._logging_steps(workflow)
        if node_instance_id is not None and node_instance_id not in steps:
            raise refused_field(
                "node_instance_id", "This workflow has no step with a Quick Log under that id"
            )
        known = (
            steps[node_instance_id]
            if node_instance_id is not None
            else set().union(*steps.values())
        )
        unknown = [outcome for outcome in outcomes if outcome not in known]
        if unknown:
            raise refused_field("outcomes", "Not an outcome the chosen step logs", unknown=unknown)

    async def _logging_steps(self, workflow: Workflow) -> dict[UUID, set[str]]:
        """The steps of the live version and of the draft that carry a Quick Log, each with the
        outcomes it can log: its output ports the Quick Log names (all, when it names none),
        and `error`, which an unrouted failure always logs."""
        graphs: list[dict[str, Any]] = []
        if workflow.current_version_id is not None:
            version = await workflow_repo.get_version(
                self.db, workflow.current_version_id, organization_id=workflow.organization_id
            )
            assert version is not None  # `current_version_id` is a version of this workflow
            graphs.append(version.graph)
        if workflow.draft_graph:
            graphs.append(workflow.draft_graph)
        steps: dict[UUID, set[str]] = {}
        for raw in graphs:
            try:
                graph = WorkflowGraph.model_validate(raw)
            except PydanticValidationError:
                raise BadRequestError(
                    message="The workflow's graph cannot be read, so its steps cannot be checked; "
                    "open it in the editor and save it again",
                    details={"workflow_id": str(workflow.id)},
                ) from None
            for node in graph.nodes:
                if node.quick_log is None:
                    continue
                try:
                    definition = _registry.get(node.definition_id, node.definition_version)
                except BadRequestError:
                    # Removed in a deploy since the graph was written: only `error` is known.
                    ports: set[str] = set()
                else:
                    ports = {
                        port.id
                        for port in instance_ports(graph, {node.id: definition})[node.id]
                        if port.kind == "output"
                    }
                    if node.quick_log.outputs is not None:
                        # Only the ports the Quick Log names write a line.
                        ports &= set(node.quick_log.outputs)
                steps.setdefault(node.id, set()).update(ports | {ERROR_PORT})
        return steps

    async def _audit(
        self,
        ctx: AuthContext,
        workflow: Workflow,
        action: str,
        rule: WorkflowLogAlertRule,
        **details: Any,
    ) -> None:
        """Field names only: what a rule counts and says stays out of the trail."""
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=action,
            target_type="workflow",
            target_id=str(workflow.id),
            details={"rule_id": str(rule.id), **details},
        )


def _check_audience(audience: list[str], user_ids: list[UUID]) -> None:
    chosen = LogAlertAudience.CHOSEN.value in audience
    if chosen and not user_ids:
        raise refused_field("user_ids", "`chosen` needs at least one member in `user_ids`")
    if user_ids and not chosen:
        raise refused_field("user_ids", "`user_ids` is only read when `audience` includes `chosen`")


def _read(
    rule: WorkflowLogAlertRule, firing: WorkflowLogAlertFiring | None
) -> WorkflowLogAlertRead:
    return WorkflowLogAlertRead(
        id=rule.id,
        workflow_id=rule.workflow_id,
        name=rule.name,
        outcomes=list(rule.outcomes),
        node_instance_id=rule.node_instance_id,
        message_contains=rule.message_contains,
        threshold=rule.threshold,
        window_minutes=rule.window_minutes,
        audience=[LogAlertAudience(a) for a in rule.audience],
        user_ids=list(rule.user_ids),
        enabled=rule.enabled,
        last_firing=None if firing is None else WorkflowLogAlertFiringRead.model_validate(firing),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )
