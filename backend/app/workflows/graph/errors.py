"""`GraphValidationError`: the one refusal shape `validate_graph` raises, and
`StepNotTestableError`, a step test's.

Built the same way `InvalidRecordError` is
(`app.services.virtual_tables.exceptions`): a list of `(field, message)`
problems, collected rather than raised on the first one, because fixing a
graph one error per round trip in the editor is the difference between a
Builder people use and one they avoid.
"""

from uuid import UUID

from app.core.exceptions import AppException, BadRequestError


class GraphValidationError(BadRequestError):
    """A workflow graph fails one or more publish-time rules (422).

    `details["fields"]` is one entry per violated rule: `field` points at
    `nodes.<id>`, `edges.<id>` or `bindings.<index>`, and `message` names the
    rule in prose a person can act on.
    """

    message = "This workflow cannot be published yet"
    code = "GRAPH_INVALID"
    status_code = 422

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        if not problems:
            raise ValueError("GraphValidationError requires at least one problem")
        fields = [{"field": field, "message": message} for field, message in problems]
        super().__init__(
            message="; ".join(f"{field}: {message}" for field, message in problems),
            details={"fields": fields},
        )


class StepNotTestableError(AppException):
    """A step cannot be tested on its own (409).

    `details["reason"]` says why: `unknown_step` when the draft has no step with
    that id, `inside_a_loop` when the step runs once per item of a loop and only
    the loop as a whole can be tested.
    """

    message = "This step cannot be tested on its own"
    code = "STEP_NOT_TESTABLE"
    status_code = 409

    def __init__(self, *, node_id: UUID, reason: str, message: str) -> None:
        super().__init__(message=message, details={"node_id": node_id, "reason": reason})
