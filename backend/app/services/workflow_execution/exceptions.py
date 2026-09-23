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
