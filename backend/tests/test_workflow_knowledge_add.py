"""`knowledge.add` around a stubbed upload: what it adds, where, and what it refuses."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.services.workflow_execution import context
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes.knowledge_add import _handler as node

pytestmark = pytest.mark.anyio

KB1, KB2 = uuid.uuid4(), uuid.uuid4()


def _dispatch() -> context.DispatchContext:
    org = uuid.uuid4()
    return context.DispatchContext(
        organization_id=org,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=org, role="owner"),
        resumed_agent_run_id=None,
    )


@dataclass
class _Upload:
    """Who may write which collection, and what the upload was handed."""

    writable: set[uuid.UUID] = field(default_factory=lambda: {KB1, KB2})
    calls: list[dict[str, Any]] = field(default_factory=list)


@pytest.fixture
def upload(monkeypatch: pytest.MonkeyPatch) -> _Upload:
    state = _Upload()
    kbs = {KB1: SimpleNamespace(id=KB1), KB2: SimpleNamespace(id=KB2)}

    async def dispatch_upload(**kwargs):
        state.calls.append(kwargs)
        return SimpleNamespace(
            id="doc-row", document_id=f"doc-{kwargs['knowledge_base_id']}", status="processing"
        )

    @asynccontextmanager
    async def session():
        yield MagicMock()

    monkeypatch.setattr(node, "get_worker_db_context", session)
    monkeypatch.setattr(
        node.knowledge_base_repo,
        "get_by_ids",
        AsyncMock(side_effect=lambda _db, ids: {i: kbs[i] for i in ids if i in kbs}),
    )
    monkeypatch.setattr(
        node,
        "writable_kb",
        AsyncMock(side_effect=lambda _db, _ctx, kb: kb.id in state.writable),
    )
    monkeypatch.setattr(
        node, "RAGDocumentService", lambda _db: SimpleNamespace(dispatch_upload=dispatch_upload)
    )
    monkeypatch.setattr(node, "get_retrieval_service", lambda: SimpleNamespace(store="store"))
    return state


async def _run(config, node_input):
    with context.dispatching_as(_dispatch()):
        return await node.handle(config, node_input)


async def test_a_text_is_added_to_each_collection_as_a_named_markdown_file(upload):
    config = node.KnowledgeAddConfig(collection_ids=(KB1, KB2))

    result = await _run(config, node.KnowledgeAddInput(title="Q3 summary: wins!", text="We won."))

    assert isinstance(result, Completed)
    assert result.output.filename == "Q3 summary wins.md"
    assert [doc.document_id for doc in result.output.documents] == [f"doc-{KB1}", f"doc-{KB2}"]
    call = upload.calls[0]
    assert call["file_data"] == b"We won." and call["replace"] is True
    assert call["vector_store"] == "store"


async def test_a_file_keeps_its_name_unless_given_a_title(upload, monkeypatch):
    ref = FileRef(file_id=uuid.uuid4(), content_type="application/pdf", byte_size=4)
    monkeypatch.setattr(
        files,
        "load",
        AsyncMock(
            return_value=files.StoredFile(
                data=b"%PDF", content_type="application/pdf", filename="deck.pdf"
            )
        ),
    )
    config = node.KnowledgeAddConfig(collection_ids=(KB1,))

    named = await _run(config, node.KnowledgeAddInput(file=ref))
    renamed = await _run(config, node.KnowledgeAddInput(file=ref, title="Board deck.pdf"))

    assert isinstance(named, Completed) and named.output.filename == "deck.pdf"
    assert isinstance(renamed, Completed) and renamed.output.filename == "Board deck.pdf"


async def test_a_file_the_run_may_not_read_fails_the_step(upload, monkeypatch):
    refusal = Failed(error=node.WorkflowError(code="FILE_NOT_FOUND", message="gone"))
    monkeypatch.setattr(files, "load", AsyncMock(return_value=refusal))

    result = await _run(
        node.KnowledgeAddConfig(collection_ids=(KB1,)),
        node.KnowledgeAddInput(
            file=FileRef(file_id=uuid.uuid4(), content_type="application/pdf", byte_size=4)
        ),
    )

    assert result is refusal


@pytest.mark.security
async def test_a_collection_the_principal_may_not_add_to_is_refused(upload):
    upload.writable = {KB1}

    result = await _run(
        node.KnowledgeAddConfig(collection_ids=(KB1, KB2)),
        node.KnowledgeAddInput(title="t", text="x"),
    )

    assert isinstance(result, Failed) and result.error.code == "KNOWLEDGE_ADD_REFUSED"


async def test_an_upload_the_platform_refuses_fails_with_its_reason(upload, monkeypatch):
    async def refuse(**_kwargs):
        raise BadRequestError(message="The organization's budget is spent")

    monkeypatch.setattr(
        node, "RAGDocumentService", lambda _db: SimpleNamespace(dispatch_upload=refuse)
    )

    result = await _run(
        node.KnowledgeAddConfig(collection_ids=(KB1,)), node.KnowledgeAddInput(title="t", text="x")
    )

    assert (
        isinstance(result, Failed) and result.error.message == "The organization's budget is spent"
    )


async def test_publishing_names_each_collection_it_may_not_add_to(upload):
    upload.writable = {KB1}
    missing = uuid.uuid4()
    config = node.KnowledgeAddConfig(collection_ids=(KB1, KB2, missing))

    problems = await node.check_resources(MagicMock(), _dispatch().auth, config)

    assert [name for name, _message in problems] == ["collection_ids.1", "collection_ids.2"]
    assert await node.check_resources(MagicMock(), _dispatch().auth, MagicMock()) == []


async def test_without_its_settings_it_says_so():
    result = await node.handle(None, None)
    assert isinstance(result, Failed) and result.error.code == "KNOWLEDGE_ADD_NOT_CONFIGURED"


def test_it_takes_a_titled_text_or_a_file_and_nothing_else():
    ref = FileRef(file_id=uuid.uuid4(), content_type="application/pdf", byte_size=4)
    for bad in ({}, {"title": "t", "text": "x", "file": ref}, {"text": "x"}):
        with pytest.raises(ValidationError):
            node.KnowledgeAddInput.model_validate(bad)
    assert node._filename("!!!") == "document.md"
