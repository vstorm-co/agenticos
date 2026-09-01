"""The `memory` capability's service layer.

Two callers, two session models, one package:

- `MemoryService` is the operator's management surface (list, create, edit,
  promote, delete), and runs on the request's session like every other service.
- the module-level `list_files`/`read_file`/`write_file`/`edit_file`/`delete_file`
  are the agent's own runtime store, each opening its own short-lived session
  because a run must not touch memory on the session it runs on (see `_native`).

External callers import from here, not from the submodules.
"""

from app.repositories.memory import FactHit
from app.services.memory._mem0 import mem0_recall, mem0_remember
from app.services.memory._native import (
    MemoryFileIndexEntry,
    MutationResult,
    delete_file,
    edit_file,
    list_files,
    read_file,
    recall,
    remember,
    write_file,
)
from app.services.memory.facade import MemoryService

__all__ = [
    "FactHit",
    "MemoryFileIndexEntry",
    "MemoryService",
    "MutationResult",
    "delete_file",
    "edit_file",
    "list_files",
    "mem0_recall",
    "mem0_remember",
    "read_file",
    "recall",
    "remember",
    "write_file",
]
