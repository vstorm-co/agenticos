"""What an upload answers when its per-file ingestion override is not legal.

The pair rule on `IngestionConfig` refuses an overlap that is not smaller than
the chunk it repeats, and its docstring says where the refusal is meant to
land: "the form is what says so". The form got `500 An unexpected error
occurred` with `details: null`, because the merge raised a raw pydantic
`ValidationError` and `register_exception_handlers` maps no such thing (#874).

Routes rather than the service alone, because the defect was route-shaped: the
service test underneath asserted the merge raised, which it always did. What
was wrong was what that raise became on the wire - and it became it twice, at
both addresses an upload can arrive at.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.resource_grant import Visibility
from app.main import app
from app.schemas.rag import RAGIngestResponse
from app.services import rag_document

pytestmark = pytest.mark.anyio

_ORGANIZATION = uuid.uuid4()
_CALLER = uuid.uuid4()
# Fixed, because it is part of a parametrized route and so part of a test id:
# a fresh one per process makes xdist workers disagree about what was collected.
_KB_ID = uuid.UUID("6a3f0b6e-9d1f-4a52-9c0b-2f5f6c1d84a7")

_TOO_MUCH_OVERLAP = json.dumps({"chunk_overlap": 4096})


@pytest.fixture(autouse=True)
def caller() -> None:
    """An owner, so a 400 here is a statement about the override.

    Which permission each route gates on is `tests/api/test_platform_routes.py`
    and the knowledge-base service's own tests; holding all of them keeps that
    out of the way.
    """
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=_CALLER,
        organization_id=_ORGANIZATION,
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )


@pytest.fixture(autouse=True)
def collection(monkeypatch: pytest.MonkeyPatch) -> KnowledgeBase:
    """A collection chunking at 512, reachable through both routes' resolvers.

    Both resolvers are stubbed rather than driven, because who may write here
    is settled before the override is read and is not what these tests are
    about. The budget check in front of the merge is stubbed for the same
    reason: it queries a session that is an `AsyncMock` in this suite.
    """
    row = KnowledgeBase(
        id=_KB_ID,
        name="Handbook",
        collection_name="handbook",
        scope=KBScope.ORG.value,
        organization_id=_ORGANIZATION,
        owner_user_id=None,
        visibility=Visibility.ORG.value,
        ingestion_config={"chunk_size": 512},
        embedding_model="text-embedding-3-large",
        embedding_dim=3072,
    )
    access = MagicMock()
    access.writable = AsyncMock(return_value=row)
    app.dependency_overrides[deps.get_collection_access_service] = lambda: access

    knowledge_bases = MagicMock()
    knowledge_bases.get_for_write = AsyncMock(return_value=row)
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: knowledge_bases

    monkeypatch.setattr(rag_document, "assert_organization_within_budget", AsyncMock())
    return row


@pytest.fixture
def store() -> MagicMock:
    """A stand-in for the vector store, so "never reached" is assertable."""
    stub = MagicMock()
    stub.create_collection = AsyncMock()
    app.dependency_overrides[deps.get_vectorstore] = lambda: stub
    return stub


def _upload() -> dict[str, Any]:
    return {"file": ("handbook.pdf", b"%PDF-1.4", "application/pdf")}


def _error(response: Any) -> dict[str, Any]:
    body: dict[str, Any] = response.json()["error"]
    return body


@pytest.mark.parametrize(
    "path",
    [
        f"{settings.API_V1_STR}/rag/collections/handbook/ingest",
        f"{settings.API_V1_STR}/kb/{_KB_ID}/documents",
    ],
)
class TestAnOverlapThatDoesNotFitInsideTheChunk:
    async def test_the_upload_is_refused_rather_than_crashing(
        self, client: AsyncClient, store: MagicMock, path: str
    ) -> None:
        """It was a 500, which reads as the platform being broken.

        4096 and 512 are each legal on their own; it is the pair that never
        advances, and the caller chose one half of it.
        """
        response = await client.post(path, files=_upload(), data={"ingestion": _TOO_MUCH_OVERLAP})

        assert response.status_code == 400
        assert _error(response)["code"] == "BAD_REQUEST"
        store.create_collection.assert_not_called()

    async def test_the_refusal_names_the_two_numbers_that_disagree(
        self, client: AsyncClient, store: MagicMock, path: str
    ) -> None:
        """`details` was `null`, so the form was told nothing at all."""
        response = await client.post(path, files=_upload(), data={"ingestion": _TOO_MUCH_OVERLAP})

        problems = _error(response)["details"]["fields"]
        assert "chunk_overlap" in problems[0]["message"]
        assert "chunk_size" in problems[0]["message"]

    async def test_the_refusal_names_a_field_the_form_can_mark_it_under(
        self, client: AsyncClient, store: MagicMock, path: str
    ) -> None:
        """`fieldProblems` reads `details["fields"]` and nothing else, so a
        refusal answered under `errors` showed a sentence and marked no input -
        the half of the answer that says which box to fix (#882)."""
        response = await client.post(path, files=_upload(), data={"ingestion": _TOO_MUCH_OVERLAP})

        problems = _error(response)["details"]["fields"]
        assert [problem["field"] for problem in problems] == ["ingestion_config"]

    async def test_no_copy_of_the_submitted_override_comes_back(
        self, client: AsyncClient, store: MagicMock, path: str
    ) -> None:
        """A refusal names the field that is wrong, not what was posted."""
        problems = _error(
            await client.post(path, files=_upload(), data={"ingestion": _TOO_MUCH_OVERLAP})
        )["details"]["fields"]

        assert all(set(problem) == {"field", "message"} for problem in problems)


@pytest.mark.parametrize(
    "path",
    [
        f"{settings.API_V1_STR}/rag/collections/handbook/ingest",
        f"{settings.API_V1_STR}/kb/{_KB_ID}/documents",
    ],
)
class TestWhatBothUploadRoutesSerialize:
    """The same schema, the same operation, the same keys on the wire.

    #560. `ingest_file` carried `response_model_exclude_none=True` and
    `upload_kb_document` did not, so `document_id` - `str | None`, and `None` on
    every accepted upload, because the id exists only once the worker has indexed
    the file - was absent from one answer and present as `null` in the other. A
    client normalising the response got a different shape from each, and the flag
    was the only use of it in the tree.

    The service is stubbed here because the question is what the *route*
    serializes: the two differed in a decorator argument, not in what they
    computed.
    """

    @pytest.fixture(autouse=True)
    def accepted_upload(self) -> MagicMock:
        service = MagicMock()
        service.dispatch_upload = AsyncMock(
            return_value=RAGIngestResponse(
                id=str(uuid.uuid4()),
                status="processing",
                filename="handbook.pdf",
                collection="handbook",
                message="File accepted. Processing in background.",
            )
        )
        app.dependency_overrides[deps.get_rag_document_service] = lambda: service
        return service

    async def test_an_accepted_upload_names_document_id_even_when_it_has_none(
        self, client: AsyncClient, store: MagicMock, path: str
    ) -> None:
        """`null` is the honest answer: the id does not exist yet."""
        response = await client.post(path, files=_upload())

        assert response.status_code == 202
        body = response.json()
        assert "document_id" in body
        assert body["document_id"] is None

    async def test_the_two_routes_answer_with_the_same_keys(
        self, client: AsyncClient, store: MagicMock, path: str
    ) -> None:
        """Every field of the schema, from either address.

        Asserted against the schema rather than against the other route's answer,
        so this fails at whichever address drifts rather than only when they
        disagree - and so adding a field to `RAGIngestResponse` that one route
        drops is caught here too.
        """
        response = await client.post(path, files=_upload())

        assert set(response.json()) == set(RAGIngestResponse.model_fields)


class TestTheSameRuleOnTheCollectionsOwnSettings:
    """The other entry point the rule guards, checked rather than assumed.

    A collection's configuration arrives as a schema field of a JSON body, so
    FastAPI validates it before the handler and `validation_exception_handler`
    answers - the pair was already refused here, named and in the envelope.
    Only the multipart override skipped that, because a form field holding JSON
    is a string until something parses it. Both name `ingestion_config` now, so
    the form marks one place whichever entry point refused (#882).
    """

    async def test_an_impossible_pair_is_named_in_the_envelope(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{settings.API_V1_STR}/kb",
            json={
                "name": "Handbook",
                "ingestion_config": {"chunk_size": 512, "chunk_overlap": 512},
            },
        )

        assert response.status_code == 422
        assert _error(response)["code"] == "VALIDATION_ERROR"
        assert _error(response)["details"]["fields"][0]["field"] == "ingestion_config"
