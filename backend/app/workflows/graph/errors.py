"""`GraphValidationError`: the one refusal shape `validate_graph` raises.

Built the same way `InvalidRecordError` is
(`app.services.virtual_tables.exceptions`): a list of `(field, message)`
problems, collected rather than raised on the first one, because fixing a
graph one error per round trip in the editor is the difference between a
Builder people use and one they avoid.
"""

from app.core.exceptions import BadRequestError


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
