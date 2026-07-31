"""The health probes, including every way they fail.

A health check nobody has watched fail is a health check that does not work: the
failure path is the entire product. So each probe here is exercised three or four
ways - it answered, it refused, it hung - and the assertions are on the `detail`
as much as the status, because a status with nothing behind it is what this
module was written to remove.

The fakes are hand-written rather than `MagicMock`: a probe is a few lines of
branching over what a query returned, and a fake that returns rows makes that
readable in a way a mock with three `side_effect` lists does not.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services import health

pytestmark = pytest.mark.anyio


class _Result:
    """One query's answer, in whichever shape the caller asks for it."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def one(self) -> Any:
        return self._value


class _Session:
    """A session that answers queries from a queue, raises, or never returns."""

    def __init__(
        self,
        *answers: Any,
        raises: Exception | None = None,
        hangs: bool = False,
    ) -> None:
        self._answers = list(answers)
        self._raises = raises
        self._hangs = hangs
        self.queries = 0

    async def execute(self, statement: Any) -> _Result:
        self.queries += 1
        if self._hangs:
            await asyncio.sleep(10)
        if self._raises is not None:
            raise self._raises
        assert self._answers, "the probe ran more queries than the fake was given"
        return _Result(self._answers.pop(0))


class _Redis:
    def __init__(
        self,
        *,
        answers: bool = True,
        raises: Exception | None = None,
        hangs: bool = False,
    ) -> None:
        self._answers = answers
        self._raises = raises
        self._hangs = hangs

    async def ping(self) -> bool:
        if self._hangs:
            await asyncio.sleep(10)
        if self._raises is not None:
            raise self._raises
        return self._answers


@pytest.fixture
def impatient(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the probe timeout so a hang is a test rather than a coffee break."""
    monkeypatch.setattr(health, "PROBE_TIMEOUT_SECONDS", 0.01)


class TestDatabaseProbe:
    async def test_a_query_that_answers_is_healthy_and_timed(self) -> None:
        check = await health.probe_database(_Session(1))  # type: ignore[arg-type]

        assert check.status == "healthy"
        assert check.detail == "SELECT 1 answered"
        assert check.latency_ms is not None

    async def test_a_refused_query_is_unhealthy_and_says_why(self) -> None:
        check = await health.probe_database(
            _Session(raises=RuntimeError("connection refused"))  # type: ignore[arg-type]
        )

        assert check.status == "unhealthy"
        assert "connection refused" in check.detail
        assert check.latency_ms is None

    async def test_a_hanging_query_is_unhealthy_rather_than_a_hanging_endpoint(
        self, impatient: None
    ) -> None:
        """The probe has to answer while the thing it probes does not.

        A readiness endpoint that blocks on a wedged database fails the kubelet's
        own timeout, which looks identical to a wedged pod - so the diagnosis is
        lost exactly when it is needed.
        """
        check = await health.probe_database(_Session(hangs=True))  # type: ignore[arg-type]

        assert check.status == "unhealthy"
        assert "did not answer within" in check.detail


class TestRedisProbe:
    async def test_a_ping_that_comes_back_is_healthy(self) -> None:
        check = await health.probe_redis(_Redis())  # type: ignore[arg-type]

        assert check.status == "healthy"
        assert check.latency_ms is not None

    async def test_an_unanswered_ping_is_unhealthy(self) -> None:
        """`RedisClient.ping` returns False when it has no connection."""
        check = await health.probe_redis(_Redis(answers=False))  # type: ignore[arg-type]

        assert check.status == "unhealthy"
        assert check.detail == "PING was not answered"

    async def test_a_client_that_raises_is_reported_not_propagated(self) -> None:
        check = await health.probe_redis(
            _Redis(raises=RuntimeError("no route to host"))  # type: ignore[arg-type]
        )

        assert check.status == "unhealthy"
        assert "no route to host" in check.detail

    async def test_a_hanging_ping_is_bounded(self, impatient: None) -> None:
        check = await health.probe_redis(_Redis(hangs=True))  # type: ignore[arg-type]

        assert check.status == "unhealthy"
        assert "did not answer within" in check.detail


class TestVectorStoreProbe:
    async def test_it_reports_the_extension_version_and_how_many_collections(self) -> None:
        check = await health.probe_vector_store(_Session("0.8.0", 3))  # type: ignore[arg-type]

        assert check.status == "healthy"
        assert "pgvector 0.8.0" in check.detail
        assert "3 collection table(s)" in check.detail

    async def test_a_missing_extension_is_unconfigured_not_broken(self) -> None:
        """A deployment that never ingests a document is not having an incident.

        It does need to know before the first upload that the upload will fail,
        which is what the detail is for.
        """
        session = _Session(None)
        check = await health.probe_vector_store(session)  # type: ignore[arg-type]

        assert check.status == "unconfigured"
        assert "not installed" in check.detail
        # No point counting embedding tables when the type they use is absent.
        assert session.queries == 1

    async def test_a_catalog_read_that_fails_is_unhealthy(self) -> None:
        check = await health.probe_vector_store(
            _Session(raises=RuntimeError("permission denied for pg_extension"))  # type: ignore[arg-type]
        )

        assert check.status == "unhealthy"
        assert "permission denied" in check.detail

    async def test_it_does_not_hang(self, impatient: None) -> None:
        check = await health.probe_vector_store(_Session(hangs=True))  # type: ignore[arg-type]

        assert check.status == "unhealthy"
        assert "did not answer within" in check.detail


class TestModelAccessProbe:
    async def test_it_counts_profiles_and_organizations_without_calling_a_provider(self) -> None:
        check = await health.probe_model_access(_Session((4, 2)))  # type: ignore[arg-type]

        assert check.status == "healthy"
        assert "4 model profile(s)" in check.detail
        assert "2 organization(s)" in check.detail
        assert "no provider was called" in check.detail

    async def test_no_usable_profile_is_unconfigured_and_names_the_consequence(self) -> None:
        """The row exists to answer "could anything here run", so 0 has to be loud.

        This is the case the old check got backwards: it read a platform-wide
        environment variable and reported healthy while no organization had a key
        a run could use.
        """
        check = await health.probe_model_access(_Session((0, 0)))  # type: ignore[arg-type]

        assert check.status == "unconfigured"
        assert "no organization has a model profile with an active key" in check.detail

    async def test_a_failed_count_is_unhealthy(self) -> None:
        check = await health.probe_model_access(
            _Session(raises=RuntimeError("relation does not exist"))  # type: ignore[arg-type]
        )

        assert check.status == "unhealthy"
        assert "relation does not exist" in check.detail

    async def test_it_does_not_hang(self, impatient: None) -> None:
        check = await health.probe_model_access(_Session(hangs=True))  # type: ignore[arg-type]

        assert check.status == "unhealthy"
        assert "did not answer within" in check.detail


class TestReadiness:
    async def test_both_dependencies_answering_is_ready(self) -> None:
        ready, checks = await health.readiness(db=_Session(1), redis=_Redis())  # type: ignore[arg-type]

        assert ready
        assert set(checks) == {"database", "redis"}

    async def test_one_dependency_down_is_not_ready(self) -> None:
        ready, checks = await health.readiness(
            db=_Session(1),  # type: ignore[arg-type]
            redis=_Redis(answers=False),  # type: ignore[arg-type]
        )

        assert not ready
        assert checks["redis"]["status"] == "unhealthy"

    async def test_the_published_payload_carries_no_reason(self) -> None:
        """Nobody authenticates to reach this, so nothing here may describe the
        network: a driver error names the host, the port and the database user.
        """
        _, checks = await health.readiness(
            db=_Session(raises=RuntimeError("connection to server at 10.0.1.7 failed")),  # type: ignore[arg-type]
            redis=_Redis(),  # type: ignore[arg-type]
        )

        assert checks["database"] == {"status": "unhealthy", "latency_ms": None}


class TestSystemHealth:
    async def test_it_reports_every_check_an_operator_can_act_on(self) -> None:
        report = await health.system_health(
            db=_Session(1, "0.8.0", 2, (1, 1)),  # type: ignore[arg-type]
            redis=_Redis(),  # type: ignore[arg-type]
        )

        assert [check.key for check in report.checks] == [
            "database",
            "redis",
            "vector_store",
            "model_access",
        ]
        assert all(check.status == "healthy" for check in report.checks)
        assert all(check.detail for check in report.checks)

    async def test_a_dead_database_does_not_produce_three_broken_services(self) -> None:
        """The two checks that read through the session are skipped, and say so.

        Running them anyway would answer with whatever the driver says about a
        session whose last query was cancelled, which reads as three unrelated
        outages instead of one.
        """
        report = await health.system_health(
            db=_Session(raises=RuntimeError("the database is gone")),  # type: ignore[arg-type]
            redis=_Redis(),  # type: ignore[arg-type]
        )

        by_key = {check.key: check for check in report.checks}
        assert by_key["database"].status == "unhealthy"
        assert by_key["vector_store"].status == "not_checked"
        assert by_key["model_access"].status == "not_checked"
        assert by_key["model_access"].detail == "not checked: the database probe failed"
