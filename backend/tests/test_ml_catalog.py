"""The ML service coverage matrix, and the page that prints it.

FA-069's first acceptance criterion is the matrix itself, so the thing under
test is not a function but a claim: every mandatory Lot 3 family appears, a row
that says it is served names an endpoint, and a row that does not says what is
missing instead of leaving a reader to infer it.

The documentation half is the same shape as
`test_capability_registry.py::TestFrontendToolCatalog` - two descriptions of one
thing, compared in both directions, so a row added to the code and not to the
page fails here rather than shipping as a page that under-reports.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.schemas.ml import ParserLiteral
from app.services.ml import parsing
from app.services.ml.catalog import SERVICE_CATALOG, DeliveryState, entry, served_ids

_PAGE = Path(__file__).resolve().parents[2] / "docs" / "ml-services.md"

MANDATORY_REQUIREMENTS = {"FA-070", "FA-071", "FA-072", "FA-073"}
"""The Lot 3 ML services B01 marks Must (initial rollout)."""


def _matrix_rows() -> list[list[str]]:
    """The rows of the coverage table in the English page."""
    lines = _PAGE.read_text().splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("| Service |"))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def test_every_mandatory_service_family_has_a_row() -> None:
    covered = {req for row in SERVICE_CATALOG for req in row.requirements}
    assert covered >= MANDATORY_REQUIREMENTS


def test_a_served_row_names_the_endpoint_that_serves_it() -> None:
    for row in SERVICE_CATALOG:
        if row.state is DeliveryState.SERVED:
            assert row.endpoint, f"{row.id} claims to be served and names no endpoint"


def test_a_row_that_is_not_served_names_no_endpoint_and_explains_itself() -> None:
    """The issue asks that a dependency be identified, not merely implied.

    A row left at `dependency` with an endpoint beside it would read as served
    at a glance, which is the exact overclaim the acceptance criteria warn about.
    """
    for row in SERVICE_CATALOG:
        if row.state is not DeliveryState.SERVED:
            assert row.endpoint is None, f"{row.id} is not served and names an endpoint"
            assert len(row.note) > 40, f"{row.id} does not say what is missing"


def test_every_row_names_what_does_the_work() -> None:
    for row in SERVICE_CATALOG:
        assert row.engine, f"{row.id} names no engine"


def test_the_ids_are_unique() -> None:
    ids = [row.id for row in SERVICE_CATALOG]
    assert len(ids) == len(set(ids))


def test_a_known_id_resolves_and_an_unknown_one_does_not() -> None:
    assert entry("ocr") is not None
    assert entry("telepathy") is None


def test_served_ids_are_the_rows_an_endpoint_answers() -> None:
    assert set(served_ids()) == {
        row.id for row in SERVICE_CATALOG if row.state is DeliveryState.SERVED
    }


def test_the_offered_parsers_are_the_ones_the_contract_lets_a_caller_name() -> None:
    """Two lists, one answer. A parser added to one and not the other is a 422."""
    assert set(get_args(ParserLiteral)) == set(parsing.ANALYSIS_PARSERS)


def test_the_page_prints_every_row_of_the_catalog() -> None:
    printed = {row[0] for row in _matrix_rows()}
    assert printed == {f"`{row.id}`" for row in SERVICE_CATALOG}


def test_the_page_states_the_same_endpoint_and_state_as_the_code() -> None:
    printed = {row[0].strip("`"): row for row in _matrix_rows()}
    for row in SERVICE_CATALOG:
        cells = printed[row.id]
        assert row.state.value in cells[3], f"{row.id}: the page disagrees about its state"
        expected = row.endpoint or ""
        assert expected in re.sub(r"[`\\]", "", cells[2]), (
            f"{row.id}: the page names a different endpoint"
        )
