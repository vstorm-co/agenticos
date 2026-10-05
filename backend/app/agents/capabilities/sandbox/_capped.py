"""A `state` workspace that cannot grow past what the platform will store.

`StateBackend` has no size limit, and it should not: it is a dictionary, and the
question of how big a dictionary may get belongs to whoever is keeping it. Here
that is a JSONB column, and an agent that writes a hundred megabytes of CSV into
one turns a chat into a row nobody can load.

The cap is applied on the way in rather than at the flush, and this is the whole
reason the subclass exists. Refusing at flush time would accept every write,
report success to the model, and then silently drop the run's work in a
`finally` block - the agent would spend its remaining turns reasoning about a
file that was never kept. Refusing at the call site gives the model an error it
can read and act on: the console tools report an `OSError` as the call's error.
"""

from __future__ import annotations

import errno
import json
from collections.abc import Iterable

from pydantic_ai_backends import FileData, StateBackend


def document_size(files: dict[str, FileData], directories: Iterable[str] = ()) -> int:
    """How many bytes storing this document costs.

    Measured as the serialised form because that is what the cap protects - the
    columns - rather than the length of the content, which ignores base64
    expansion and the per-file bookkeeping. The directories are stored beside the
    files and count too: every parent of a deep path is one, so a path nested a
    few thousand levels would otherwise grow the row past the ceiling uncounted.
    """
    stored = json.dumps(files, ensure_ascii=False) + json.dumps(
        sorted(directories), ensure_ascii=False
    )
    return len(stored.encode("utf-8"))


class CappedStateBackend(StateBackend):
    """A `StateBackend` document that refuses to exceed a byte ceiling.

    Only a write grows the document by more than a path, so only a write is
    measured: it is performed, measured, and rolled back when it takes the
    document over the line, so the document is never left in a state the store
    would reject.
    """

    def __init__(
        self,
        files: dict[str, FileData] | None = None,
        directories: Iterable[str] | None = None,
        *,
        max_bytes: int,
    ) -> None:
        super().__init__(files, directories)
        self._max_bytes = max_bytes

    def write_bytes(self, path: str, data: bytes) -> None:
        """Store a file, unless that takes the document past the ceiling.

        Raises:
            OSError: `ENOSPC`, with what to tell the model, when it would.
        """
        # A shallow copy restores it: a write binds a new `FileData` to the path
        # rather than changing the stored one, and records new parents in
        # `directories` without touching the others.
        files_before = dict(self.files)
        directories_before = set(self.directories)
        super().write_bytes(path, data)
        size = document_size(self.files, self.directories)
        if size <= self._max_bytes:
            return
        self.files.clear()
        self.files.update(files_before)
        self.directories.clear()
        self.directories.update(directories_before)
        # The measure is the absolute size rather than the change, so a document
        # that is *already* over the ceiling - `SANDBOX_STATE_MAX_BYTES` lowered
        # beneath one stored under the old value - can only shrink. "Shorten or
        # overwrite", not "delete": the console offers no delete, and naming one
        # would send the model looking for something that is not there.
        raise OSError(
            errno.ENOSPC,
            f"The workspace is full: this would take it to {size} bytes, over the "
            f"{self._max_bytes}-byte limit. Shorten or overwrite something first, or "
            "keep large intermediate results out of the workspace.",
        )

    def __repr__(self) -> str:
        return f"<CappedStateBackend(files={len(self.files)}, max={self._max_bytes})>"
