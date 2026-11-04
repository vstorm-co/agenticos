"""A capability's configuration refused at the field it is about.

A `model_validator` that raises `ValueError` reports its error with no location,
because the rule spans several fields. Publish validation then names the whole
`config`, which the Builder's `capabilityConfigErrors` reads as no field at all:
the author sees "Invalid configuration" and nothing marked (found reviewing #2265).
A rule that does belong to one field - the voice, the model, the resolution -
raises it there instead, as a `ValidationError` located at that field.
"""

from collections.abc import Sequence

from pydantic import ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

Refusal = tuple[tuple[str | int, ...], str, object]
"""Where a value was refused, why, and the value: `(("voices", 2, "id"), msg, value)`."""


def refused_at(title: str, refusals: Sequence[Refusal]) -> ValidationError:
    """A `ValidationError` naming each refused field at its own location.

    Args:
        title: The model the error is raised from, as Pydantic titles it.
        refusals: Each refused value, by its location, with the sentence the
            author reads.

    Returns:
        The error, for the validator to raise.
    """
    return ValidationError.from_exception_data(
        title,
        [
            InitErrorDetails(
                type=PydanticCustomError("refused", "{reason}", {"reason": reason}),
                loc=loc,
                input=value,
            )
            for loc, reason, value in refusals
        ],
    )
