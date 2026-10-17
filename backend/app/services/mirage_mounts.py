"""The knowledge-base and sync-source folders of a Mirage terminal, for one run.

A capability must not fetch what it reads, so the runner resolves these the way
it resolves an agent's collection names: from the bound knowledge bases, in
this organization, before the model is called. Two kinds of folder come out:

- `/knowledge/<base>/` - each indexed document of a bound knowledge base, as
  the text its parse produced. Listed here, up front, because it is one query;
  a document is read from the vector store when a command opens it.
- `/sources/<source>/` - the files behind those bases' synced sources, read
  through the platform's own connector with the credential the source syncs
  with. Listed on the first command that reaches the folder, because a listing
  is a request to somebody else's store.

A website source is not offered: its pages are already documents under
`/knowledge`, and crawling a site again from a shell command is a slow way to
read what the base already holds.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.mirage import MountedTree, TreeFile, TreeUnavailable
from app.agents.spec import AgentSpec
from app.core.config import settings
from app.core.permissions import AuthContext
from app.core.secret_kinds import StorableSecret
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.sync_source import SyncSource
from app.repositories import knowledge_base_repo, rag_document_repo, sync_source_repo
from app.services.organization_secret import OrganizationSecretService
from app.services.rag.connectors import CONNECTOR_REGISTRY, BaseSyncConnector, RemoteFile
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vectorstore import BaseVectorStore, unpooled_vector_store

logger = logging.getLogger(__name__)

# Connectors whose listing is a tree of files. A website is not one - see above.
FILE_STORES = frozenset({"s3", "gdrive", "sharepoint", "git"})

# The largest source file a command may read. A read lands in memory whole, and
# a terminal is for text a model can use, not for a video in a bucket.
MAX_FILE_BYTES = 20 * 1024 * 1024

# Shorter than this, a chunk boundary that happens to repeat is not taken for
# the splitter's overlap.
_MIN_OVERLAP = 20


def _agent_vector_store() -> BaseVectorStore:
    # Unpooled for the knowledge capability's reason: a run's tools execute on
    # the API's loop in one process and on a flow's loop in another (#1079).
    return unpooled_vector_store(settings.rag, EmbeddingService(settings.rag))


def _folder(name: str, taken: set[str]) -> str:
    """A folder name for `name` that is a path segment and not already taken."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "untitled"
    folder, counter = base, 1
    while folder.lower() in taken:
        counter += 1
        folder = f"{base}-{counter}"
    taken.add(folder.lower())
    return folder


def _unique(path: str, taken: set[str]) -> str:
    """`path`, or `path` with `~N` before its extension when an earlier file holds it."""
    candidate, counter = path, 1
    pure = PurePosixPath(path)
    while candidate in taken:
        counter += 1
        candidate = str(pure.with_name(f"{pure.stem}~{counter}{pure.suffix}"))
    taken.add(candidate)
    return candidate


def _segments(path: str) -> str:
    """`path` with nothing in it that climbs out of, or collapses, the folder."""
    parts = [part for part in path.replace("\\", "/").split("/") if part not in ("", ".", "..")]
    return "/".join(parts) or "untitled"


def stitched(chunks: Sequence[str]) -> str:
    """A document's text from its chunks, with each splitter overlap kept once.

    The splitter repeats the tail of one chunk at the head of the next - "as
    much as fits", so the length varies - and joined naively every boundary
    would say its last sentence twice, which a `grep -c` would count. Where no
    overlap is found, a page or section boundary, the chunks are separated by a
    blank line.
    """
    text = ""
    for chunk in chunks:
        if not text:
            text = chunk
            continue
        text += _after_overlap(text, chunk)
    return text


def _after_overlap(text: str, chunk: str) -> str:
    probe = chunk[:_MIN_OVERLAP]
    if len(probe) == _MIN_OVERLAP:
        tail = text[-len(chunk) :]
        start = tail.find(probe)
        while start != -1:
            # The earliest match is the longest overlap.
            if chunk.startswith(tail[start:]):
                return chunk[len(tail) - start :]
            start = tail.find(probe, start + 1)
    return "\n\n" + chunk


def _source_path(source: SyncSource, remote: RemoteFile) -> str:
    """Where a source's file sits under its folder: its key or path where it has one."""
    if source.connector_type == "s3":
        # `s3://<bucket>/<key>`: the key keeps the bucket's own folders.
        return _segments(remote.source_path.split("://", 1)[-1].split("/", 1)[-1])
    if source.connector_type == "git":
        return _segments(remote.id)
    return _segments(remote.name)


class MirageMountService:
    """Resolves the folders a Mirage binding asks for, for one run."""

    def __init__(
        self,
        db: AsyncSession,
        vector_store: Callable[[], BaseVectorStore] = _agent_vector_store,
    ) -> None:
        self.db = db
        self.secrets = OrganizationSecretService(db)
        self._vector_store = vector_store

    async def trees(
        self, ctx: AuthContext, spec: AgentSpec, *, knowledge: bool, sources: bool
    ) -> tuple[MountedTree, ...]:
        """The `/knowledge` and `/sources` folders of the agent's bound knowledge bases.

        Bases are this organization's (or deployment-wide) and bound to the
        spec, exactly the set the agent's knowledge search reaches; a base
        deleted since publish is skipped, as it is there.
        """
        found = await knowledge_base_repo.get_by_ids(self.db, spec.collection_ids)
        bases = [
            kb
            for kb_id in spec.collection_ids
            if (kb := found.get(kb_id)) is not None
            and kb.organization_id in (None, ctx.organization_id)
        ]
        trees: list[MountedTree] = []
        if knowledge:
            taken: set[str] = set()
            for kb in bases:
                trees.append(await self._knowledge_tree(kb, _folder(kb.name, taken)))
        if sources:
            trees.extend(await self._source_trees(ctx, bases))
        return tuple(trees)

    async def _knowledge_tree(self, kb: KnowledgeBase, folder: str) -> MountedTree:
        # Each path to its document's id in the vector store.
        documents: dict[str, str] = {}
        taken: set[str] = set()
        for document in await rag_document_repo.get_indexed_for_kb(self.db, kb.id):
            if document.vector_document_id is not None:
                documents[_unique(_segments(document.filename), taken)] = (
                    document.vector_document_id
                )
        store: BaseVectorStore | None = None
        collection, tenant = kb.collection_name, kb.vector_tenant

        async def list_files() -> list[TreeFile]:
            # No size: what a file holds is its parsed text, not the upload.
            return [TreeFile(path=path) for path in documents]

        async def read_file(path: str) -> bytes:
            nonlocal store
            store = store or self._vector_store()
            chunks = await store.get_document_chunks(collection, documents[path], tenant)
            return stitched([chunk.content for chunk in chunks]).encode()

        return MountedTree(
            path=f"/knowledge/{folder}/",
            describe=f'knowledge base "{kb.name}", each document as its parsed text',
            list_files=list_files,
            read_file=read_file,
        )

    async def _source_trees(
        self, ctx: AuthContext, bases: Sequence[KnowledgeBase]
    ) -> list[MountedTree]:
        found: list[SyncSource] = []
        for kb in bases:
            # This organization's sources only, a deployment-wide base included:
            # another tenant's source on a shared base is not this agent's to read.
            found += await sync_source_repo.get_all(
                self.db,
                organization_id=ctx.organization_id,
                collection_name=kb.collection_name,
                is_active=True,
            )
        found = [source for source in found if source.connector_type in FILE_STORES]
        credentials = await self.secrets.resolve_for_bindings(
            ctx, [source.secret_id for source in found if source.secret_id is not None]
        )
        taken: set[str] = set()
        return [
            _source_tree(
                source,
                credentials.get(source.secret_id) if source.secret_id is not None else None,
                _folder(source.name, taken),
            )
            for source in found
        ]


def _source_tree(source: SyncSource, credential: StorableSecret | None, folder: str) -> MountedTree:
    connector: BaseSyncConnector = CONNECTOR_REGISTRY[source.connector_type]()
    config = dict(source.config)
    files: dict[str, RemoteFile] = {}

    async def list_files() -> list[TreeFile]:
        listing = await connector.list_files(config, credential)
        taken: set[str] = set()
        for remote in listing.files:
            files[_unique(_source_path(source, remote), taken)] = remote
        return [TreeFile(path=path, size=remote.size) for path, remote in files.items()]

    async def read_file(path: str) -> bytes:
        remote = files[path]
        if remote.size is not None and remote.size > MAX_FILE_BYTES:
            raise TreeUnavailable(_too_large(path))
        with tempfile.TemporaryDirectory(prefix="mirage-") as scratch:
            local = await connector.download_file(remote, Path(scratch), config, credential)
            data = await asyncio.to_thread(local.read_bytes)
        if len(data) > MAX_FILE_BYTES:
            raise TreeUnavailable(_too_large(path))
        return data

    async def close() -> None:
        try:
            await connector.aclose()
        except Exception:
            # A clone left behind is the worker's temp directory's to clear; it
            # is no reason to fail a run that has already answered.
            logger.warning("mirage_source_close_failed", extra={"source": str(source.id)})

    return MountedTree(
        path=f"/sources/{folder}/",
        describe=f'the files of sync source "{source.name}" ({source.connector_type})',
        list_files=list_files,
        read_file=read_file,
        close=close,
    )


def _too_large(path: str) -> str:
    return f"{path} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB and is not read here"
