"""A `state` workspace that cannot grow past what the platform will store.

`StateBackend` has no size limit, and it should not: it is a dictionary, and the
question of how big a dictionary may get belongs to whoever is keeping it. Here
that is a JSONB column, and an agent that writes a hundred megabytes of CSV into
one turns a chat into a row nobody can load.

The cap is applied on the way in rather than at the flush, and this is the whole
reason the wrapper exists. Refusing at flush time would accept every write,
report success to the model, and then silently drop the run's work in a
`finally` block - the agent would spend its remaining turns reasoning about a
file that was never kept. Refusing at the call site gives the model an error it
can read and act on, which is what the backend protocol asks of a failure.
"""

from __future__ import annotations

import json
from typing import cast

from pydantic_ai_backends import (
    EditResult,
    FileData,
    FileInfo,
    GrepMatch,
    StateBackend,
    WriteResult,
)


def document_size(files: dict[str, FileData]) -> int:
    """How many bytes storing this document costs.

    Measured as the serialised form because that is what the cap protects - the
    column - rather than the length of the content, which ignores base64
    expansion and the per-file bookkeeping.
    """
    return len(json.dumps(files, ensure_ascii=False).encode("utf-8"))


class CappedStateBackend:
    """A `StateBackend` that refuses to exceed a byte ceiling.

    Delegates everything that cannot grow the document. `write` and `edit` are
    performed, measured, and rolled back when they take it over the line, so the
    document is never left in a state the store would reject.
    """

    def __init__(self, backend: StateBackend, *, max_bytes: int) -> None:
        self._backend = backend
        self._max_bytes = max_bytes

    @property
    def files(self) -> dict[str, FileData]:
        return self._backend.files

    def _snapshot(self) -> dict[str, FileData]:
        """A restorable copy of the document.

        One level deep is enough and worth the precision, and it holds because of
        what the library does rather than by luck: `StateBackend.write` builds a
        fresh `FileData` and rebinds `files[path]`, and `edit` assigns
        `stored["content"] = ...` - both replace the list rather than mutating it,
        so copying each entry's mapping preserves the previous value while the
        line lists stay shared. `files` is the live dict too, so `_restore`
        reaches the backend rather than a copy of it. Deep-copying a
        four-megabyte document on every write would cost more than the write.
        """
        return {path: cast(FileData, dict(entry)) for path, entry in self._backend.files.items()}

    def _restore(self, snapshot: dict[str, FileData]) -> None:
        self._backend.files.clear()
        self._backend.files.update(snapshot)

    def _too_large(self) -> str | None:
        """Whether the document is now over the line, and what to tell the model.

        The measure is the absolute size rather than the change, so a document
        that is *already* over the ceiling can only be brought back under in one
        move - a partial cleanup is refused and rolled back with it. Left that way
        deliberately: getting there needs `SANDBOX_STATE_MAX_BYTES` lowered
        beneath a document that was stored under the old value, which is an
        operator's change and not something an agent can do to itself. A delta
        check would be more code for a case that only a downgrade reaches.
        """
        size = document_size(self._backend.files)
        if size <= self._max_bytes:
            return None
        # "Shorten or overwrite", not "delete": `StateBackend` exposes no delete
        # and `WORKSPACE_TOOLS` declares none, so there is no tool for it. Naming
        # one would send the model looking for something that is not there.
        return (
            f"The workspace is full: this would take it to {size} bytes, over the "
            f"{self._max_bytes}-byte limit. Shorten or overwrite something first, or "
            "keep large intermediate results out of the workspace."
        )

    def write(self, path: str, content: str | bytes) -> WriteResult:
        snapshot = self._snapshot()
        result = self._backend.write(path, content)
        if result.error is not None:
            return result
        if (reason := self._too_large()) is not None:
            self._restore(snapshot)
            return WriteResult(error=reason)
        return result

    def edit(
        self, path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        snapshot = self._snapshot()
        result = self._backend.edit(path, old_string, new_string, replace_all)
        if result.error is not None:
            return result
        if (reason := self._too_large()) is not None:
            self._restore(snapshot)
            return EditResult(error=reason)
        return result

    def exists(self, path: str) -> bool:
        return self._backend.exists(path)

    def ls_info(self, path: str) -> list[FileInfo]:
        return self._backend.ls_info(path)

    def read_bytes(self, path: str) -> bytes:
        return self._backend.read_bytes(path)

    def read(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        return self._backend.read(path, offset, limit)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return self._backend.glob_info(pattern, path)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        ignore_hidden: bool = True,
    ) -> list[GrepMatch] | str:
        return self._backend.grep_raw(pattern, path, glob, ignore_hidden)

    def __repr__(self) -> str:
        return f"<CappedStateBackend(files={len(self._backend.files)}, max={self._max_bytes})>"
