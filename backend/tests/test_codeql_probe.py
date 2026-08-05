"""Throwaway probe for #220. Not for merging.

Each function writes one of the shapes `github-code-quality` flags, so the pull
request answers three questions at once: which of them actually reach the review
thread path, and whether either inline suppression syntax (`# codeql[...]` on the
line before, `# lgtm[...]` on the line itself) stops one arriving.
"""

import asyncio
from typing import Protocol

import pytest

pytestmark = pytest.mark.anyio


async def _noop() -> None:
    return None


async def test_bare_await_with_no_suppression() -> None:
    task = asyncio.create_task(_noop())
    await task


async def test_bare_await_with_codeql_comment() -> None:
    task = asyncio.create_task(_noop())
    # codeql[py/ineffectual-statement]  # noqa: ERA001
    await task


async def test_bare_await_with_lgtm_comment() -> None:
    task = asyncio.create_task(_noop())
    await task  # lgtm[py/ineffectual-statement]


class _Stub(Protocol):
    def probe(self) -> None: ...


def _first_even(values: list[int]) -> int:
    for value in values:
        if value % 2 == 0:
            return value
    pytest.fail("no even value in the list")


def test_a_protocol_body_and_a_no_return_fallthrough() -> None:
    assert _first_even([1, 2]) == 2
    assert _Stub.probe is not None
