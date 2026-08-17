"""The backend's dashboard widget mirror equals the frontend registry.

A saved layout stores widget ids and spans, and the API validates both on write
against :data:`WIDGET_IDS` and :data:`SPANS`. Those two sets are a copy of what
`frontend/src/lib/dashboard/registry.ts` declares, and a copy drifts: rename a
widget on one side and a layout the other side saves is either rejected for a
widget that exists or accepted for one that does not.

So this reads the union types straight out of the registry the frontend
actually ships and asserts the mirror matches in both directions - a widget in
the registry with no backend entry, and a backend entry for a widget the
registry dropped, each fail here naming the id. It is the backend's test because
the write validation is the backend's, the same way the tool-catalog parity
check is (see `tests/test_capability_registry.py`).
"""

import re
from pathlib import Path

from app.schemas.dashboard_layout import ROWS, SPANS, WIDGET_IDS

REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "dashboard" / "registry.ts"
)


def _union_members(source: str, type_name: str) -> frozenset[str]:
    """The string-literal members of an exported `type X = "a" | "b" | ...` union."""
    match = re.search(rf"export type {type_name} =(.*?);", source, flags=re.DOTALL)
    assert match, f"could not find `export type {type_name}` in {REGISTRY_PATH.name}"
    return frozenset(re.findall(r'"([^"]+)"', match.group(1)))


def test_the_widget_ids_match_the_frontend_registry() -> None:
    source = REGISTRY_PATH.read_text(encoding="utf-8")
    frontend = _union_members(source, "WidgetId")

    assert sorted(frontend - WIDGET_IDS) == [], (
        "these widgets are in the frontend registry but not in the backend "
        "WIDGET_IDS mirror - a layout naming one would be rejected on save"
    )
    assert sorted(WIDGET_IDS - frontend) == [], (
        "these widget ids are in the backend mirror but not in the frontend "
        "registry - nothing will ever render them"
    )


def test_the_spans_match_the_frontend_registry() -> None:
    source = REGISTRY_PATH.read_text(encoding="utf-8")
    frontend = _union_members(source, "Span")

    assert frontend == SPANS, (
        "the closed span set drifted from the frontend registry; write validation "
        "would accept a width the grid cannot render, or reject one it can"
    )


def test_the_rows_match_the_frontend_registry() -> None:
    source = REGISTRY_PATH.read_text(encoding="utf-8")
    frontend = _union_members(source, "Rows")

    assert frontend == ROWS, (
        "the closed height set drifted from the frontend registry; write validation "
        "would accept a height the grid cannot render, or reject one it can"
    )
