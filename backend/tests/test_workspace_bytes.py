"""`file_response`'s range handling, for a caller holding the bytes already.

The generated-media route no longer comes through here - it streams the range off
the store (#2310) - but a route that has the bytes in hand answers a player the
same way, and the two must not drift: the same header gets the same answer.
"""

import pytest

from app.api.routes.v1._workspace_bytes import file_response


@pytest.mark.parametrize(
    ("asked", "body", "content_range"),
    [("bytes=0-3", b"0123", "bytes 0-3/10"), ("bytes=-3", b"789", "bytes 7-9/10")],
)
def test_a_range_is_answered_with_its_slice(asked: str, body: bytes, content_range: str):
    response = file_response(
        b"0123456789", path="video.mp4", download=False, byte_range=asked, serves_ranges=True
    )

    assert response.status_code == 206
    assert response.body == body
    assert response.headers["content-range"] == content_range
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"


def test_a_range_past_the_end_is_not_satisfiable():
    response = file_response(b"0123", path="video.mp4", download=False, byte_range="bytes=4-")

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */4"


def test_a_route_that_passes_no_range_promises_none():
    response = file_response(b"0123", path="report.pdf", download=True)

    assert response.status_code == 200
    assert "accept-ranges" not in response.headers
    assert response.headers["content-disposition"].startswith("attachment")
