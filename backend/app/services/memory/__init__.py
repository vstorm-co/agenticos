"""The `memory_files` capability's service layer.

Two callers, two session models, one package:

- `MemoryService` is the erasure surface - forgetting one person, or clearing one
  agent - and runs on the request's session like every other service.
- the module-level `list_files`/`read_file`/`write_file`/`edit_file`/`delete_file`
  are the agent's own runtime store, each opening its own short-lived session
  because a run must not touch memory on the session it runs on (see `_native`).

There is no operator authoring here. Notes are written by the agent; anything a
person writes belongs in `context` (#1470).

External callers import from here, not from the submodules.
"""

from app.services.memory._native import (
    MemoryFileIndexEntry,
    delete_file,
    edit_file,
    list_files,
    read_file,
    write_file,
)
from app.services.memory.facade import MemoryService

__all__ = [
    "MemoryFileIndexEntry",
    "MemoryService",
    "delete_file",
    "edit_file",
    "list_files",
    "read_file",
    "write_file",
]
