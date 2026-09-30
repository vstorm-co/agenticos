"""Virtual Tables: the one service behind every table surface."""

from app.services.virtual_tables import (
    trigger_dependents as _trigger_dependents,  # noqa: F401 - registers its checker
)
from app.services.virtual_tables.facade import TableViewService, VirtualTableService
from app.services.virtual_tables.records import RecordWrite

__all__ = [
    "RecordWrite",
    "TableViewService",
    "VirtualTableService",
]
