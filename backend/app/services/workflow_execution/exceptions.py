"""Domain exceptions for workflow execution."""

from uuid import UUID

from app.core.exceptions import AppException


class WorkflowRunNotFoundError(AppException):
    """No run with this id in this organization (404)."""

    message = "Workflow run not found"
    code = "WORKFLOW_RUN_NOT_FOUND"
    status_code = 404

    def __init__(self, *, run_id: UUID) -> None:
        super().__init__(details={"run_id": run_id})


class WorkflowAdmissionQuotaError(AppException):
    """Too much node work is already queued or running to admit another run (429).

    Not the per-minute run limit (`limit_workflow_run`): this bounds the node
    work one organization, and one caller within it, may hold on the shared
    runner at once, so repeated starts below the rate limit cannot grow a
    backlog that starves other tenants (#1907). `scope` names which ceiling was
    hit (`organization` or `principal`). Retried once running work drains, so it
    is a 429 like the rate limit rather than a permanent refusal.
    """

    message = (
        "Too much workflow work is already in flight. "
        "Wait for running work to finish and try again."
    )
    code = "WORKFLOW_ADMISSION_QUOTA_EXCEEDED"
    status_code = 429

    def __init__(self, *, scope: str, limit: int, outstanding: int, requested: int) -> None:
        super().__init__(
            details={
                "scope": scope,
                "limit": limit,
                "outstanding": outstanding,
                "requested": requested,
            }
        )


class WorkflowArchivedError(AppException):
    """A write, or a new run, was attempted on an archived workflow (409)."""

    message = "This workflow is archived and cannot be edited"
    code = "WORKFLOW_ARCHIVED"
    status_code = 409

    def __init__(self, *, workflow_id: UUID, message: str | None = None) -> None:
        super().__init__(message=message, details={"workflow_id": workflow_id})


class WorkflowTriggerMismatchError(AppException):
    """The run was asked for through a door the live version's trigger is not (409).

    A workflow starts from one trigger, and only that trigger's surface starts
    its published version: a workflow that starts from a webhook is not run by
    hand, and one that starts from a chat message is not run from the API. A
    test run of the draft takes any trigger.
    """

    message = "This workflow does not start this way"
    code = "WORKFLOW_TRIGGER_MISMATCH"
    status_code = 409

    def __init__(self, *, workflow_id: UUID, trigger: str | None, door: str) -> None:
        super().__init__(details={"workflow_id": workflow_id, "trigger": trigger, "door": door})


class WorkflowNotRunnableError(AppException):
    """Nothing to run: no published version (`real`) or no draft graph (`test`) (409)."""

    message = "This workflow has no runnable graph"
    code = "WORKFLOW_NOT_RUNNABLE"
    status_code = 409

    def __init__(self, *, workflow_id: UUID) -> None:
        super().__init__(details={"workflow_id": workflow_id})


class WorkflowRunNotRetryableError(AppException):
    """Only a run that failed, was cancelled or ran out of budget is retried (409)."""

    message = "Only a run that failed, was cancelled or ran out of budget can be retried"
    code = "WORKFLOW_RUN_NOT_RETRYABLE"
    status_code = 409

    def __init__(self, *, run_id: UUID, status: str) -> None:
        super().__init__(details={"run_id": run_id, "status": status})


class WorkflowRunAlreadyTerminalError(AppException):
    """The run already ended; there is nothing left to cancel (409)."""

    message = "This run has already ended"
    code = "WORKFLOW_RUN_TERMINAL"
    status_code = 409

    def __init__(self, *, run_id: UUID, status: str) -> None:
        super().__init__(details={"run_id": run_id, "status": status})


class WorkflowDispatchRefusedError(AppException):
    """A node's dispatch can never succeed, however often it is retried.

    Raised while `dispatcher.begin_attempt` resolves a node's call, and never
    reaches a client: the dispatcher ends the run with `code` as its
    `WorkflowRun.error` code. Retrying would fail identically, and leaving the
    claim in place would have `workflow-reconcile` resubmit it for ever.
    """

    message = "This node can never be dispatched"
    code = "DISPATCH_REFUSED"


class WorkflowGraphUnresolvableError(WorkflowDispatchRefusedError):
    """The run's graph, or the node a `NodeRun` names in it, no longer resolves."""

    message = "This run's graph no longer resolves"
    code = "GRAPH_UNRESOLVABLE"

    def __init__(self, *, run_id: UUID) -> None:
        super().__init__(details={"run_id": run_id})


class NodeDefinitionMissingError(WorkflowDispatchRefusedError):
    """The node's pinned `(id, version)` is not registered in this deployment."""

    message = "This node's definition is not registered in this deployment"
    code = "NODE_DEFINITION_MISSING"

    def __init__(self, *, node_id: str, version: int) -> None:
        super().__init__(details={"node_id": node_id, "version": version})


class NodeHandlerMissingError(WorkflowDispatchRefusedError):
    """The node's definition is registered without a handler to call."""

    message = "This node's definition has no handler to run"
    code = "NODE_HANDLER_MISSING"

    def __init__(self, *, node_id: str, version: int) -> None:
        super().__init__(details={"node_id": node_id, "version": version})


class InvalidBindingError(WorkflowDispatchRefusedError):
    """A bound value can never satisfy the target node's config or input schema.

    For a template, `field` and `placeholder` name the placeholder that resolved
    to nothing: the step it reads, by its name, and the path into its output.
    """

    message = "A bound value does not satisfy this node's input schema"
    code = "INVALID_BINDING"

    def __init__(
        self, *, node_instance_id: UUID, field: str | None = None, placeholder: str | None = None
    ) -> None:
        details: dict[str, object] = {"node_instance_id": node_instance_id}
        message = None
        if placeholder is not None:
            details |= {"field": field, "placeholder": placeholder}
            message = f"The template in {field} has nothing for {placeholder}"
        super().__init__(message=message, details=details)


class PrincipalRevokedError(WorkflowDispatchRefusedError):
    """The account a run acts as may no longer run its workflow."""

    message = "The account this run acts as can no longer run this workflow"
    code = "PRINCIPAL_REVOKED"

    def __init__(self) -> None:
        super().__init__(details={})


class WorkflowRunInputInvalidError(AppException):
    """The run's input does not fit the fields its Manual or API trigger declares (422).

    `details["problems"]` names each field that is missing, of the wrong type,
    not one of a choice's options, or not declared at all.
    """

    message = "The run's input does not fit the fields this workflow asks for"
    code = "WORKFLOW_RUN_INPUT_INVALID"
    status_code = 422

    def __init__(self, *, problems: list[dict[str, str]]) -> None:
        super().__init__(details={"problems": problems})


class WorkflowRunInputTooLargeError(AppException):
    """The payload a run was started with is larger than the deployment allows (413)."""

    message = "The run's input is too large"
    code = "WORKFLOW_RUN_INPUT_TOO_LARGE"
    status_code = 413

    def __init__(self, *, limit: int, size: int) -> None:
        super().__init__(details={"limit_bytes": limit, "size_bytes": size})


class WorkflowNotWaitingError(AppException):
    """Nothing in the run waits for a call to its resume link now (409).

    Before a Wait step waiting for one is reached, after it went on - an earlier
    call woke it, or its time ran out - or once the run has ended. The caller may
    try again later only in the first case, which it can tell from its own flow.
    """

    message = "Nothing in this workflow run is waiting for a call"
    code = "WORKFLOW_NOT_WAITING"
    status_code = 409

    def __init__(self, *, run_id: UUID) -> None:
        super().__init__(details={"run_id": run_id})


class WorkflowWebhookUnansweredError(AppException):
    """A webhook's run ended badly before any step answered its sender (500).

    Only for a graph that answers its deliveries (`webhook.respond`): the sender
    is waiting for that answer, and a run that failed, was cancelled or ran out of
    budget first will never give one. A run that succeeded without reaching the
    step answers `202`, as a delivery to a graph without one does.
    """

    message = "The workflow run ended before it answered this webhook"
    code = "WORKFLOW_WEBHOOK_UNANSWERED"
    status_code = 500

    def __init__(self, *, run_id: UUID, status: str) -> None:
        super().__init__(details={"run_id": run_id, "status": status})
