"""Virtual Tables: the one service behind every table surface."""

from app.services.virtual_tables import (
    trigger_dependents as _trigger_dependents,  # noqa: F401 - registers its checker
)
from app.services.virtual_tables.computed import Reach, reach
from app.services.virtual_tables.facade import TableViewService, VirtualTableService
from app.services.virtual_tables.records import RecordWrite
from app.services.virtual_tables.table_views import BoundView

__all__ = [
    "BoundView",
    "Reach",
    "RecordWrite",
    "TableViewService",
    "VirtualTableService",
    "reach",
]
