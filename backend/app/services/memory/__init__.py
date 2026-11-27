"""The `memory_files` capability's service layer.

Two callers, two session models, one package:

- `MemoryService` is the erasure surface - forgetting one person, or clearing one
  agent - and runs on the request's session like every other service.
- the module-level `list_files`/`read_file`/`write_file`/`edit_file`/`delete_file`
  are the agent's own runtime store, each opening its own short-lived session
  because a run must not touch memory on the session it runs on (see `_native`).

Notes are owned by their subject. The subject can edit or restore a body and
choose whether maintenance may update it.

External callers import from here, not from the submodules.
"""

from app.services.memory import _claims as claims
from app.services.memory import _runtime as runtime
from app.services.memory import extraction
from app.services.memory._native import (
    ErasedDuringRun,
    MemoryFileIndexEntry,
    NoteChangedDuringRead,
    NoteObjectUnavailable,
    delete_file,
    edit_file,
    list_files,
    read_file,
    read_file_revision,
    write_file,
)
from app.services.memory.facade import MemoryService

__all__ = [
    "ErasedDuringRun",
    "MemoryFileIndexEntry",
    "MemoryService",
    "NoteChangedDuringRead",
    "NoteObjectUnavailable",
    "claims",
    "delete_file",
    "edit_file",
    "extraction",
    "list_files",
    "read_file",
    "read_file_revision",
    "runtime",
    "write_file",
]
