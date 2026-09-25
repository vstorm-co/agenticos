"""Virtual Tables: the one service behind every table surface."""

from app.services.virtual_tables.facade import VirtualTableService
from app.services.virtual_tables.records import RecordWrite

__all__ = ["RecordWrite", "VirtualTableService"]
