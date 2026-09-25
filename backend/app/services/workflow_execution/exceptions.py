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


class WorkflowNotRunnableError(AppException):
    """Nothing to run: no published version (`real`) or no draft graph (`test`) (409)."""

    message = "This workflow has no runnable graph"
    code = "WORKFLOW_NOT_RUNNABLE"
    status_code = 409

    def __init__(self, *, workflow_id: UUID) -> None:
        super().__init__(details={"workflow_id": workflow_id})


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
    """A bound value can never satisfy the target node's config or input schema."""

    message = "A bound value does not satisfy this node's input schema"
    code = "INVALID_BINDING"

    def __init__(self, *, node_instance_id: UUID) -> None:
        super().__init__(details={"node_instance_id": node_instance_id})


class PrincipalRevokedError(WorkflowDispatchRefusedError):
    """The account a run acts as may no longer run its workflow."""

    message = "The account this run acts as can no longer run this workflow"
    code = "PRINCIPAL_REVOKED"

    def __init__(self) -> None:
        super().__init__(details={})
