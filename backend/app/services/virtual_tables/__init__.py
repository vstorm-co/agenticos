"""Virtual Tables: the one service behind every table surface."""

from app.services.virtual_tables import (
    trigger_dependents as _trigger_dependents,  # noqa: F401 - registers its checker
)
from app.services.virtual_tables.computed import Reach, named_by, reach
from app.services.virtual_tables.deadline import ReadDeadline
from app.services.virtual_tables.facade import TableViewService, VirtualTableService
from app.services.virtual_tables.records import BoundRows, RecordWrite
from app.services.virtual_tables.table_views import BoundView
from app.services.virtual_tables.tables import TableSource

__all__ = [
    "BoundRows",
    "BoundView",
    "Reach",
    "ReadDeadline",
    "RecordWrite",
    "TableSource",
    "TableViewService",
    "VirtualTableService",
    "named_by",
    "reach",
]
