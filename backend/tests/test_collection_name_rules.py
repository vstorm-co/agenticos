"""What a caller-supplied collection name is allowed to be, in one place.

The store built two identifiers out of that string and judged it with two
different rules, neither of which bounded its length. `_table` - which every
read, write and drop funnels through - accepted a leading digit and a name of
any size at all; `create_collection` refused the digit and allowed 64
characters. Postgres keeps 63 bytes of an identifier and truncates the rest
without a word, so `rag_` plus 60 characters is another collection's table and
`rag_<name>_embedding_idx` past 45 is another collection's index (#368). Two of
the three refusals were `ValueError`, which no handler maps, so a name the
server understood and declined arrived as a 500 (#371).

This covers the function all of that collapsed into. The model-table case it
also answers has its own file (`tests/test_reserved_collection_names.py`,
#345); what is here is the shape rule, the length bound, the reserved set, and
the two things that have to keep agreeing with them - the identifiers the store
actually builds, and the names `KnowledgeBaseService` derives when a caller
supplies none.
"""

from __future__ import annotations

import pytest

import app.db.models  # noqa: F401  - registers every table on the metadata
from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.db.vector_tables import (
    MAX_COLLECTION_NAME_LENGTH,
    VECTOR_INDEX_SUFFIX,
    VECTOR_TABLE_PREFIX,
    validate_collection_name,
)
from app.services.knowledge_base import _derive_collection_name
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio

_POSTGRES_KEEPS = 63
"""`NAMEDATALEN - 1`, the number this whole file exists because of."""


def _refuse(name: str) -> BadRequestError:
    with pytest.raises(BadRequestError) as refused:
        validate_collection_name(name, metadata=Base.metadata)
    return refused.value


class TestTheShapeRule:
    @pytest.mark.parametrize(
        "name",
        [
            "foo-bar",
            "foo bar",
            "foo;drop table rag_documents",
            'foo"bar',
            "",
            "_leading_underscore",
            "2024_reports",
            "ünïcode",
        ],
    )
    def test_a_name_that_is_not_a_bare_identifier_is_refused(self, name: str) -> None:
        """Bare, because the store interpolates it into DDL unquoted.

        The leading-digit case is the one that was not obviously a bug:
        `rag_2024_reports` is a legal identifier, so the prefix hides that the
        name is not. Refusing it is what lets every other reader of a collection
        name assume the name alone is usable.
        """
        assert _refuse(name).details == {"collection": name}

    @pytest.mark.parametrize("name", ["Handbook", "handBook", "HANDBOOK", "Documents_Archive"])
    def test_a_name_with_any_upper_case_is_refused(self, name: str) -> None:
        """Postgres folds an unquoted identifier, so `Handbook` *is* `handbook`.

        Nothing above the database can see that. `claim` compares whole strings,
        so one organization's `handbook` and another's `Handbook` are two rows
        the platform believes are two collections, sharing one table's vectors -
        #368's collision reached by spelling instead of by length, and the length
        bound does not touch it.

        The first version of this branch accepted `Handbook` and asserted it as
        an ordinary name, which would have shipped the hole with a test holding
        it open. What made that visible is that the code already knew: the
        reserved check and `collides_with_model_table` both folded, so
        `Documents` was refused while `Handbook` was not.

        Refused rather than lower-cased on the way in - storing a name the caller
        did not type is the reinterpretation this whole rule exists to avoid.
        """
        assert _refuse(name).details == {"collection": name}

    @pytest.mark.parametrize("name", ["handbook", "h", "a_1_b_2", "documents_archive"])
    def test_an_ordinary_name_is_accepted(self, name: str) -> None:
        validate_collection_name(name, metadata=Base.metadata)


class TestTheLengthBound:
    def test_a_name_at_the_bound_is_accepted_and_one_past_it_is_not(self) -> None:
        at_the_bound = "a" * MAX_COLLECTION_NAME_LENGTH

        validate_collection_name(at_the_bound, metadata=Base.metadata)

        refused = _refuse(at_the_bound + "a")
        assert refused.details == {
            "collection": at_the_bound + "a",
            "max_length": MAX_COLLECTION_NAME_LENGTH,
        }

    def test_two_names_that_would_share_one_table_are_both_refused(self) -> None:
        """The pair from #368: 60 characters agreeing on the first 59.

        `rag_` plus either is 64 bytes, truncated to the same 63, so the second
        collection created would have read, written and dropped the first one's
        vectors - across organizations, since a collection name is unique to
        nobody.
        """
        shared = "a" * 59

        assert _refuse(shared + "b").details["max_length"] == MAX_COLLECTION_NAME_LENGTH
        assert _refuse(shared + "c").details["max_length"] == MAX_COLLECTION_NAME_LENGTH

    def test_the_bound_is_what_every_identifier_the_store_builds_survives(self) -> None:
        """The bound is derived, and this is the derivation stated the other way.

        Asserting the arithmetic rather than the number 45: the index suffix is
        what makes the table's own 59 too generous, and a suffix that changes
        without this constant changing is the truncation back.
        """
        longest = "a" * MAX_COLLECTION_NAME_LENGTH
        table = f"{VECTOR_TABLE_PREFIX}{longest}"

        assert len(table) <= _POSTGRES_KEEPS
        assert len(f"{table}{VECTOR_INDEX_SUFFIX}") == _POSTGRES_KEEPS


class TestTheReservedSet:
    @pytest.mark.parametrize("name", ["all", "ALL", "All"])
    def test_a_reserved_name_is_refused_however_it_is_spelled(self, name: str) -> None:
        """Every spelling is refused; only the lower-case one gets this far.

        `ALL` and `All` are refused by the shape rule before the reserved set is
        consulted, which is why that set no longer folds. Both spellings are
        asserted anyway: what a caller needs is that the name does not work, and
        pinning it here means a future relaxation of the shape rule fails a test
        rather than quietly reopening `ALL`.
        """
        assert _refuse(name).details == {"collection": name}

    def test_a_name_that_merely_contains_a_reserved_one_is_fine(self) -> None:
        validate_collection_name("all_hands", metadata=Base.metadata)


class TestTheDerivedName:
    """A name nobody typed still has to satisfy the rule everybody else does.

    It did not: the slug is built from a display name, so `2024 Reports` derived
    `2024_reports`, which `create_collection` refuses and `_table` used to
    accept. Nothing broke only because the KB create path reached neither - it
    wrote a row and stopped. Converging the two validators is what would have
    made an ingest into that collection fail, so the derivation is fixed in the
    same change.
    """

    @pytest.mark.parametrize(
        "display_name",
        [
            "Handbook",
            "2024 Reports",
            "  ",
            "!!!",
            "Ünïcödé",
            "A " * 200,
            "9",
        ],
    )
    def test_every_derived_name_passes_the_rule(self, display_name: str) -> None:
        validate_collection_name(_derive_collection_name(display_name), metadata=Base.metadata)

    def test_a_display_name_starting_with_a_digit_still_derives_something_usable(self) -> None:
        derived = _derive_collection_name("2024 Reports")

        assert derived.startswith("kb_2024_reports_")

    def test_a_long_display_name_is_trimmed_rather_than_refused(self) -> None:
        """The suffix is the point of the derivation, so the slug is what gives way."""
        derived = _derive_collection_name("Quarterly " * 40)

        assert len(derived) == MAX_COLLECTION_NAME_LENGTH


class TestTheStorePathsAgree:
    """The regression for #368: creation and every other method judged alike.

    A name `create_collection` refused used to reach `_table` regardless, and
    `_table` is what `search`, `insert_document`, `get_collection_info` and
    `delete_collection` build their SQL with. Asserted on the destructive one
    and the creating one, because a rule that holds on both ends holds on the
    methods between them - they call the same function with the same argument.

    Neither call reaches a session: `_table` runs first in both, which is what
    makes a store built with `__new__` a fair test rather than a lucky one.
    """

    @pytest.mark.parametrize(
        "name", ["2024_reports", "foo-bar", "a" * (MAX_COLLECTION_NAME_LENGTH + 1)]
    )
    async def test_a_name_creation_refuses_cannot_reach_the_drop_path_either(
        self, name: str
    ) -> None:
        store = PgVectorStore.__new__(PgVectorStore)

        with pytest.raises(BadRequestError):
            await store.create_collection(name, organization_id=None)
        with pytest.raises(BadRequestError):
            await store.delete_collection(name)
