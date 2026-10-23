"""A Redis outage behind the chat's live views is logged once a while, not per socket."""

import logging

import pytest

from app.services import redis_view

LOGGER = logging.getLogger("tests.redis_view")


@pytest.fixture(autouse=True)
def _fresh() -> None:
    redis_view._logged_at.clear()
    redis_view._unlogged.clear()


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == LOGGER.name]


def test_an_outage_is_logged_once_and_counts_what_it_left_out(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hundreds of sockets retrying used to log a traceback each, every time."""
    now = [100.0]
    monkeypatch.setattr(redis_view.time, "monotonic", lambda: now[0])
    error = ConnectionError("redis went away")

    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        for _ in range(5):
            redis_view.failed(LOGGER, "chat_room_join_failed", error)
        now[0] += redis_view.LOG_EVERY_SECONDS
        redis_view.failed(LOGGER, "chat_room_join_failed", error)

    logged = _warnings(caplog)
    assert [record.getMessage() for record in logged] == ["chat_room_join_failed"] * 2
    assert [record.__dict__["unlogged"] for record in logged] == [0, 4]
    assert logged[0].exc_info is not None
    assert logged[0].exc_info[1] is error


def test_each_kind_of_failure_is_logged_on_its_own(caplog: pytest.LogCaptureFixture) -> None:
    error = ConnectionError("redis went away")
    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        redis_view.failed(LOGGER, "chat_room_join_failed", error)
        redis_view.failed(LOGGER, "live_turn_publish_failed", error)

    assert [record.getMessage() for record in _warnings(caplog)] == [
        "chat_room_join_failed",
        "live_turn_publish_failed",
    ]
