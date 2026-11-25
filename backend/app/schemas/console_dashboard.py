"""Organization layouts are shared presentation, never a person's pinned filters."""

from typing import Self

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import BaseSchema
from app.schemas.dashboard_layout import (
    MAX_ENTRIES,
    DashboardLayoutUpdate,
    StoredWidgetPlacement,
    WidgetPlacement,
)


class OrganizationDashboardUpdate(DashboardLayoutUpdate):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def no_private_filters(self) -> Self:
        for entry in self.entries:
            if (
                isinstance(entry, WidgetPlacement)
                and entry.options is not None
                and (entry.options.agent_id is not None or entry.options.user_id is not None)
            ):
                raise ValueError(
                    "Organization defaults cannot pin a person or agent; remove those filters first"
                )
        return self


class StoredOrganizationDashboard(BaseSchema):
    entries: list[StoredWidgetPlacement] = Field(max_length=MAX_ENTRIES)
