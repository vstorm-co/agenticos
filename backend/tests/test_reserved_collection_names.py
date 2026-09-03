"""A collection may not be named after a table the models own.

The store names a collection's table by prefixing it, so a collection called
`documents` is the model table tracking every ingested document in the
deployment. Nothing refused the name, and every method reached that table:
`get_collection_info` answered with the deployment-wide document count,
`_ensure_collection` created an HNSW index on a column that table has no
version of, and `delete_collection` issued `DROP TABLE IF EXISTS` on it (#345).

Two guards, because there are two ways in and only one of them is a route. The
store refuses in `_table`, which every one of its methods funnels through -
including the one `rag-drop documents --yes` reaches with no service, no route
and no permission in between. `KnowledgeBaseService.create` refuses as well,
because it writes a row without going near the store, and a row is enough: the
collision is waiting for the first ingest.

Neither guard knows the name `documents`. Both ask whether the models declare
that table, which is what keeps `documents_archive` a collection somebody may
have.

Both now ask it as one of four questions about a caller-chosen name -
`tests/test_collection_name_rules.py` covers the other three and the single
function all of them live in.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.db.models  # noqa: F401  - registers every table on the metadata
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.base import Base
from app.db.vector_tables import VECTOR_TABLE_PREFIX, collides_with_model_table
from app.schemas.knowledge_base import KnowledgeBaseCreate
from app.services.knowledge_base import KnowledgeBaseService
from app.services.rag.config import DEFAULT_COLLECTION_NAME
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _not_reserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """A create reaches `claim`, which reads the teardown-reservation repo (#1362);
    mock it at the boundary so a name is free unless a test says otherwise."""
    from app.repositories import collection_teardown_repo

    monkeypatch.setattr(collection_teardown_repo, "is_reserved", AsyncMock(return_value=False))


def _modelled_collection_names() -> list[str]:
    """The collection name each prefixed model table would answer to."""
    return sorted(
        name.removeprefix(VECTOR_TABLE_PREFIX)
        for name in Base.metadata.tables
        if name.startswith(VECTOR_TABLE_PREFIX)
    )


class _Session:
    """Records the statements a store method issues, and answers nothing."""

    def __init__(self, executed: list[str]) -> None:
        self._executed = executed

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def execute(self, statement: Any, parameters: Any = None) -> MagicMock:
        self._executed.append(str(statement))
        return MagicMock()

    async def commit(self) -> None:
        return None


def _store() -> tuple[PgVectorStore, list[str]]:
    """A store with no engine, and the list of statements it reaches SQL with."""
    executed: list[str] = []
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = MagicMock(return_value=_Session(executed))
    return store, executed


def test_the_predicate_answers_for_every_prefixed_model_table() -> None:
    """Parametrised over the metadata, so a second one added later is covered.

    `documents` is the one that made this a bug; asserting it is present keeps
    the case from quietly emptying if the model is renamed.
    """
    modelled = _modelled_collection_names()

    assert "documents" in modelled
    for name in modelled:
        assert collides_with_model_table(name, metadata=Base.metadata)


def test_a_name_no_model_declares_is_an_ordinary_collection() -> None:
    assert not collides_with_model_table("company_handbook", metadata=Base.metadata)


def test_the_predicate_folds_the_way_postgres_does() -> None:
    """It answers for a spelling no caller can supply any more, and must.

    `validate_collection_name` refuses upper case outright, so nothing in the
    product reaches this with `Documents`. The predicate is public and has its
    own contract - `alembic/env.py` reasons with its sibling, and a caller with
    a name from somewhere other than a request has no shape rule in front of it.
    Its folding is therefore its own guarantee rather than a consequence of the
    validator's order, and this is what keeps it one if the order changes.
    """
    assert collides_with_model_table("Documents", metadata=Base.metadata)


def test_the_default_collection_name_is_not_a_model_table() -> None:
    """The default is what an omitted `--collection` and an omitted field get.

    It was `documents`, which is why the documented first-run ingest aimed at
    the tracking table. Pinned here rather than trusted, so a future default -
    or a future model table named after this one - fails a test instead of a
    deployment.
    """
    assert not collides_with_model_table(DEFAULT_COLLECTION_NAME, metadata=Base.metadata)


async def test_creating_a_collection_named_after_a_model_table_is_refused() -> None:
    store, executed = _store()

    with pytest.raises(BadRequestError) as refused:
        await store.create_collection("documents")

    assert refused.value.details == {"collection": "documents", "table": "rag_documents"}
    assert executed == []


async def test_dropping_one_never_reaches_the_database() -> None:
    """The regression, and the reason it is asserted on the statements.

    A test that only asserted the table survives would pass without the fix:
    `ingestion_spend.rag_document_id` references `rag_documents`, so Postgres
    refuses the `DROP` and the route swallows the error. That refusal belongs to
    a foreign key on an unrelated table and is one `CASCADE` from being gone.
    What this fix does is not issue the statement.
    """
    store, executed = _store()

    with pytest.raises(BadRequestError):
        await store.delete_collection("documents")

    assert executed == []


async def test_a_spelling_postgres_folds_onto_a_model_table_is_refused_too() -> None:
    """`rag_Documents` is not a distinct table; unquoted, Postgres folds it.

    The store interpolates the collection into its DDL unquoted, so
    `DROP TABLE IF EXISTS rag_Documents` drops the tracking table exactly as the
    lower-case spelling would. A reserved-name check comparing the name as typed
    would have refused one and handed the other the `DROP`.

    Two rules refuse it now and the shape rule gets there first, because upper
    case is refused outright - `Handbook` and `handbook` are one table too, and
    that one has no model table to be caught by. `collides_with_model_table`
    still folds, and `test_the_predicate_folds_the_way_postgres_does` still
    asserts it: it is a public predicate a caller may reach without the shape
    rule in front of it.
    """
    store, executed = _store()

    with pytest.raises(BadRequestError):
        await store.delete_collection("Documents")

    assert executed == []


async def test_a_collection_whose_name_only_starts_like_one_still_works() -> None:
    """`documents_archive` is a collection somebody may reasonably create.

    Reserving the literal `documents`, or anything beginning with it, would
    answer #345 and take a real collection with it - the case
    `tests/test_collection_listing.py` pins on the read side.
    """
    store, executed = _store()

    await store.delete_collection("documents_archive")

    assert executed == ["DROP TABLE IF EXISTS rag_documents_archive"]


class TestKnowledgeBaseCreate:
    """The other door: a row written with a name the store never sees.

    It reaches the refusal through
    :meth:`app.services.collection_access.CollectionAccessService.claim` rather
    than through a check of its own, which is why every test here also patches
    the lookup that method makes. That is the fix for #367 read from this side:
    the KB service used to have a private model-table check and *no* claim, so
    the name was judged for one of the four things that can be wrong with it and
    never compared against the rows that already hold it.
    """

    @staticmethod
    def _ctx() -> AuthContext:
        return AuthContext(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            role=OrgRoleName.OWNER.value,
            is_app_admin=False,
        )

    @staticmethod
    def _unclaimed() -> AsyncMock:
        """The name is held by nobody, so only the rule about it can refuse."""
        return AsyncMock(return_value=[])

    async def test_a_knowledge_base_cannot_claim_a_model_tables_name(self) -> None:
        service = KnowledgeBaseService(MagicMock())
        created = AsyncMock()

        with (
            patch("app.repositories.knowledge_base_repo.create", new=created),
            patch(
                "app.repositories.knowledge_base_repo.list_by_collection_name",
                new=self._unclaimed(),
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await service.create(
                KnowledgeBaseCreate(name="Handbook", collection_name="documents"),
                ctx=self._ctx(),
            )

        assert refused.value.details == {"collection": "documents", "table": "rag_documents"}
        created.assert_not_awaited()

    async def test_a_near_miss_name_is_still_created(self) -> None:
        service = KnowledgeBaseService(MagicMock(execute=AsyncMock()))
        created = AsyncMock(return_value=MagicMock())

        with (
            patch("app.repositories.knowledge_base_repo.create", new=created),
            patch(
                "app.repositories.knowledge_base_repo.list_by_collection_name",
                new=self._unclaimed(),
            ),
        ):
            await service.create(
                KnowledgeBaseCreate(name="Handbook", collection_name="documents_archive"),
                ctx=self._ctx(),
            )

        assert created.await_args is not None
        assert created.await_args.kwargs["collection_name"] == "documents_archive"
