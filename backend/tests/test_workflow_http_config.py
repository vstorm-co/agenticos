"""The HTTP steps' authentication and paging settings: what each refuses."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.workflows.nodes._http import HttpAuth, with_query
from app.workflows.nodes.http_request import HttpPagination, HttpRequestConfig

_SECRET = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize(
    "auth",
    [
        {"kind": "query", "secret_id": _SECRET},
        {"kind": "bearer", "secret_id": _SECRET, "query_name": "api_key"},
        {"kind": "none", "query_name": "api_key"},
        {"kind": "query", "secret_id": _SECRET, "query_name": "bad name"},
    ],
    ids=["no-parameter", "parameter-for-bearer", "parameter-without-auth", "not-a-name"],
)
def test_query_authentication_names_its_parameter_and_only_it_does(auth: dict[str, Any]):
    with pytest.raises(ValidationError):
        HttpAuth.model_validate(auth)


def test_query_authentication_with_its_parameter_is_accepted():
    auth = HttpAuth(kind="query", secret_id=_SECRET, query_name="api_key")  # ty: ignore[invalid-argument-type]
    assert auth.query_name == "api_key"


@pytest.mark.parametrize(
    "pagination",
    [
        {"mode": "page", "param": "page"},
        {"mode": "next_url", "items_path": "data"},
        {"mode": "cursor", "items_path": "data", "next_path": "meta.next"},
        {"mode": "page", "items_path": "data"},
        {"mode": "page", "items_path": "data[", "param": "page"},
        {"mode": "page", "items_path": "data", "param": "page", "max_pages": 101},
    ],
    ids=["no-items", "no-next", "cursor-no-param", "page-no-param", "bad-path", "too-many"],
)
def test_paging_needs_what_its_mode_reads(pagination: dict[str, Any]):
    with pytest.raises(ValidationError):
        HttpPagination.model_validate(pagination)


def test_only_a_get_pages():
    with pytest.raises(ValidationError, match="Only a GET"):
        HttpRequestConfig.model_validate(
            {
                "method": "POST",
                "url": "https://api.example.com",
                "pagination": {"mode": "page", "items_path": "data", "param": "page"},
            }
        )


def test_a_query_parameter_replaces_the_one_the_url_had():
    assert with_query("https://x.example.com/a?page=1&q=z", "page", "2") == (
        "https://x.example.com/a?q=z&page=2"
    )


def _page() -> Any:
    from app.workflows.nodes.http_request._handler import _Page

    return _Page(url="https://api.example.com/items", response=None, raw=b"")  # ty: ignore[invalid-argument-type]


def test_a_page_whose_items_the_path_cannot_read_fails_and_one_with_none_has_none():
    from app.workflows.contracts.results import Failed
    from app.workflows.nodes.http_request._handler import _items

    paging = HttpPagination(mode="page", items_path="abs(data)", param="page")
    unreadable = _items(paging, {"data": "text"})
    assert isinstance(unreadable, Failed) and unreadable.error.code == "PAGE_ITEMS_UNREADABLE"
    assert _items(HttpPagination(mode="page", items_path="data", param="page"), {}) == []


def test_a_next_page_the_path_cannot_read_ends_the_paging():
    from app.workflows.nodes.http_request._handler import _next

    paging = HttpPagination(mode="next_url", items_path="data", next_path="abs(next)")
    assert _next(paging, _page(), {"next": "text"}, base="https://x.example.com", number=1) is None
