"""What a caller may say about retention, and what they are told back.

The read is deliberately three things rather than one number per class: what this
organization asked for, what it actually gets, and what the deployment allows.
A settings page showing only the last of those cannot explain why a period it
displays is not the period somebody typed - which is the whole of the confusion a
ceiling creates.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.retention import (
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    RETENTION_CLASSES,
    RetentionClass,
)

#: A period per class, classes absent where nothing has been said about them.
RetentionDays = dict[RetentionClass, int | None]


def _validated(value: RetentionDays) -> RetentionDays:
    """Refuse a period outside the bounds, naming the class that is wrong."""
    for name, days in value.items():
        if days is None:
            continue
        if days < MIN_RETENTION_DAYS or days > MAX_RETENTION_DAYS:
            raise ValueError(
                f"{name}: a period is between {MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS} days"
            )
    return value


class RetentionUpdate(BaseModel):
    """What an organization asks to keep, per class.

    A class left out is left alone; a class set to `null` is "keep for ever",
    said deliberately. The two are different answers and the API keeps them
    apart, which is why this is a mapping rather than six optional fields.
    """

    retention_days: RetentionDays = Field(default_factory=dict)

    @field_validator("retention_days")
    @classmethod
    def _bounds(cls, value: RetentionDays) -> RetentionDays:
        return _validated(value)


class RetentionRead(BaseModel):
    """The three answers a settings page needs to show one row per class."""

    model_config = ConfigDict(from_attributes=True)

    classes: list[RetentionClass] = Field(default_factory=lambda: list(RETENTION_CLASSES))
    """The classes, in the order they are shown."""

    requested: RetentionDays
    """What this organization set. A class absent means it has said nothing."""

    effective: RetentionDays
    """What actually sweeps, after the deployment's defaults, ceiling and floor."""

    ceilings: RetentionDays
    """The deployment's per-class maximum. A class absent has none."""

    audit_floor_days: int
    """The shortest an audit entry may live here. An organization may only lengthen it."""

    conflicts: list[RetentionClass] = Field(default_factory=list)
    """Classes whose deployment settings contradict each other, for the operator.

    Reported rather than resolved: an audit ceiling below the audit floor asks
    for a trail kept six years and deleted after one, and picking one of the two
    would leave a deployment behaving unlike its own settings page.
    """
