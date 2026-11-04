"""`knowledge.add`: put a text or a file into knowledge collections.

The write half of `knowledge.search`: what a run produced - a summary, a report,
a downloaded document - becomes something agents can find. It goes through the
same upload the console's collection page uses (`RAGDocumentService.dispatch_upload`),
so it is parsed, chunked and embedded by the collection's own settings, counted
against the organization's budget, and queued rather than waited for.

The document is named, and a second run that adds the same name replaces it
rather than adding a twin - which is also what makes a retry safe.
"""

import logging
import re
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.knowledge._search import get_retrieval_service
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.session import get_worker_db_context
from app.repositories import knowledge_base_repo
from app.services.collection_access import writable_kb
from app.services.rag_document import RAGDocumentService
from app.services.workflow_execution import context
from app.services.workflow_execution.errors import workflow_error
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError

logger = logging.getLogger(__name__)

MAX_BYTES = 50_000_000
"""The largest file one step adds - the console's own upload limit."""


class KnowledgeAddConfig(BaseModel):
    """Which collections the document goes into."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    collection_ids: tuple[UUID, ...] = Field(
        min_length=1,
        max_length=5,
        json_schema_extra={"x-resource": "collection"},
        description="The knowledge collections to add the document to.",
    )


class KnowledgeAddInput(BaseModel):
    """A text with a title, or a file - exactly one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str | None = Field(
        default=None,
        max_length=200,
        description="The document's name. Required with a text; a file keeps its own name without it.",
    )
    text: str | None = Field(default=None, min_length=1, max_length=5_000_000)
    file: FileRef | None = None

    @model_validator(mode="after")
    def _one_document(self) -> Self:
        if (self.text is None) == (self.file is None):
            raise ValueError("Bind a text or a file, not both")
        if self.text is not None and not self.title:
            raise ValueError("A text needs a title to be found by")
        return self


class AddedDocument(BaseModel):
    """One collection's copy of the document, as queued."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    collection_id: UUID
    document_id: str | None
    status: str


class KnowledgeAddOutput(BaseModel):
    """What was queued, one entry per collection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    documents: tuple[AddedDocument, ...]


def _filename(title: str) -> str:
    """A title as a Markdown file name - what a text is ingested as."""
    stem = re.sub(r"[^\w\- ]+", "", title).strip() or "document"
    return f"{stem}.md"


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a collection the graph's author may not add to."""
    if not isinstance(config, KnowledgeAddConfig):
        return []
    found = await knowledge_base_repo.get_by_ids(db, config.collection_ids)
    problems = []
    for index, collection_id in enumerate(config.collection_ids):
        kb = found.get(collection_id)
        if kb is None or not await writable_kb(db, ctx, kb):
            problems.append(
                (f"collection_ids.{index}", "This collection does not exist or cannot be added to")
            )
    return problems


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, KnowledgeAddConfig) or not isinstance(node_input, KnowledgeAddInput):
        return Failed(
            error=WorkflowError(
                code="KNOWLEDGE_ADD_NOT_CONFIGURED",
                message="This step needs collections and a text or a file",
            )
        )
    if node_input.file is not None:
        stored = await files.load(node_input.file, max_bytes=MAX_BYTES)
        if isinstance(stored, Failed):
            return stored
        data = stored.data
        filename = node_input.title or stored.filename or "document"
    else:
        data = (node_input.text or "").encode()
        filename = _filename(node_input.title or "")
    current = context.current()
    added: list[AddedDocument] = []
    try:
        async with get_worker_db_context() as db:
            found = await knowledge_base_repo.get_by_ids(db, config.collection_ids)
            service = RAGDocumentService(db)
            for collection_id in config.collection_ids:
                kb = found.get(collection_id)
                if kb is None or not await writable_kb(db, current.auth, kb):
                    return Failed(
                        error=WorkflowError(
                            code="KNOWLEDGE_ADD_REFUSED",
                            message="A collection does not exist or cannot be added to",
                            details={"collection_id": str(collection_id)},
                        )
                    )
                queued = await service.dispatch_upload(
                    ctx=current.auth,
                    collection=kb,
                    file_data=data,
                    filename=filename,
                    replace=True,
                    vector_store=get_retrieval_service().store,
                    organization_id=current.organization_id,
                    knowledge_base_id=kb.id,
                )
                added.append(
                    AddedDocument(
                        collection_id=collection_id,
                        document_id=queued.document_id or queued.id,
                        status=queued.status,
                    )
                )
    except AppException as exc:
        return Failed(error=workflow_error(exc))
    return Completed[KnowledgeAddOutput](
        output=KnowledgeAddOutput(filename=filename, documents=tuple(added))
    )
