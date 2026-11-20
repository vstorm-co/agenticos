"""What an answer should say, and whether it says it.

Shared by workflow evals and the failure-learning loop: both write cases as
an expectation (`{kind, field, value}`) and judge an answer against it. The
kinds stay `equals|contains|not_contains`; `field` is a path into the output -
`text`, `category`, `structured.amount` - read as text, or the whole output
as JSON when empty.
"""

from typing import Literal

from pydantic import Field

from app.schemas.base import BaseSchema

ExpectationKind = Literal["contains", "not_contains", "equals"]


class EvalExpectation(BaseSchema):
    """What an answer should say.

    Matching ignores case and the space around the value: an eval checks what
    a model said, not how it was capitalised.
    """

    kind: ExpectationKind = "contains"
    field: str | None = Field(
        default="text",
        max_length=200,
        pattern=r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$",
        description="Where in the output to look; the whole output when null",
    )
    value: str = Field(min_length=1, max_length=2000)
