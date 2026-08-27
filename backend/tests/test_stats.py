"""StatsService - window arithmetic and the scope decision.

The SQL itself is proven against a real database in
tests/integration/test_usage_stats_sql.py; here the repository boundary is
mocked and what is under test is everything the service adds on top of it:
the inclusive-dates-to-half-open-window conversion, the previous-window
arithmetic, the zero-filled day series, and the rule that org scope demands
runs:view while own scope demands only a caller.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, ValidationError
from app.core.permissions import AuthContext, OrgRoleName
from app.repositories.agent_run import WindowAggregates
from app.services.stats import StatsService, resolve_window

pytestmark = pytest.mark.anyio


_AT = datetime(2026, 8, 4, 9, 30, tzinfo=UTC)


def _ctx(role: str = OrgRoleName.OWNER.value) -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role)


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    """Every aggregate stubbed at the repository boundary, individually settable."""
    mocks: dict[str, AsyncMock] = {}
    for name, value in (
        ("count_runs", 0),
        ("runs_by_day", []),
        ("runs_by_dimension", []),
        ("runs_by_agent", []),
        ("latency_percentiles_ms", (None, None)),
        ("sum_cost_window", Decimal(0)),
        ("cost_by_provider_window", []),
        ("count_distinct_users", 0),
        ("count_pending_approval_runs", 0),
        ("usage_by_version", []),
        ("usage_by_user", []),
        ("runs_by_hour", []),
    ):
        mock = AsyncMock(return_value=value)
        monkeypatch.setattr(f"app.services.stats.agent_run_repo.{name}", mock)
        mocks[name] = mock

    # `usage` reads its window's scalars from one `window_aggregates` query now;
    # this stub composes the answer from the four per-aggregate mocks above, so a
    # test still sets `count_runs`, `sum_cost_window`, `latency_percentiles_ms` or
    # `count_distinct_users` and controls the field it maps to - one call per
    # window, the same order the standalone calls used to run in.
    async def _window_aggregates(db: object = None, **kwargs: object) -> WindowAggregates:
        total = await mocks["count_runs"](db, **kwargs)
        cost = await mocks["sum_cost_window"](db, **kwargs)
        distinct = await mocks["count_distinct_users"](db, **kwargs)
        p50, p95 = await mocks["latency_percentiles_ms"](db, **kwargs)
        return WindowAggregates(
            total=total, cost_usd=cost, distinct_users=distinct, p50_ms=p50, p95_ms=p95
        )

    window_aggregates = AsyncMock(side_effect=_window_aggregates)
    monkeypatch.setattr("app.services.stats.agent_run_repo.window_aggregates", window_aggregates)
    mocks["window_aggregates"] = window_aggregates

    # The previous window takes the lighter count+cost aggregate; delegate it to the
    # same two mocks so a test still drives it through `count_runs`/`sum_cost_window`.
    async def _window_totals(db: object = None, **kwargs: object) -> tuple[int, Decimal]:
        return await mocks["count_runs"](db, **kwargs), await mocks["sum_cost_window"](db, **kwargs)

    window_totals = AsyncMock(side_effect=_window_totals)
    monkeypatch.setattr("app.services.stats.agent_run_repo.window_totals", window_totals)
    mocks["window_totals"] = window_totals

    ingestion = AsyncMock(return_value=Decimal(0))
    monkeypatch.setattr("app.services.stats.ingestion_spend_repo.sum_cost_window", ingestion)
    mocks["ingestion_sum_cost_window"] = ingestion
    member_count = AsyncMock(return_value=0)
    monkeypatch.setattr("app.services.stats.member_repo.count_for_org", member_count)
    mocks["count_for_org"] = member_count
    version_ratings = AsyncMock(return_value={})
    monkeypatch.setattr(
        "app.services.stats.message_rating_repo.rating_counts_by_version", version_ratings
    )
    mocks["rating_counts_by_version"] = version_ratings
    scoped_summary = AsyncMock(
        return_value={
            "total_ratings": 0,
            "like_count": 0,
            "dislike_count": 0,
            "average_rating": 0.0,
            "with_comments": 0,
            "ratings_by_day": [],
        }
    )
    monkeypatch.setattr(
        "app.services.stats.message_rating_repo.get_rating_summary_scoped", scoped_summary
    )
    mocks["get_rating_summary_scoped"] = scoped_summary
    return mocks


class TestResolveWindow:
    def test_inclusive_dates_become_a_half_open_utc_window(self) -> None:
        window = resolve_window(date(2026, 7, 1), date(2026, 7, 31))

        assert window.start == datetime(2026, 7, 1, tzinfo=UTC)
        # 23:59:59 of the last day counts; midnight of the next day does not.
        assert window.end == datetime(2026, 8, 1, tzinfo=UTC)

    def test_a_single_day_window_spans_exactly_one_day(self) -> None:
        window = resolve_window(date(2026, 7, 15), date(2026, 7, 15))

        assert window.end - window.start == datetime(2026, 7, 16, tzinfo=UTC) - datetime(
            2026, 7, 15, tzinfo=UTC
        )

    def test_defaults_are_the_last_thirty_days_ending_today(self) -> None:
        window = resolve_window(None, None, today=date(2026, 8, 5))

        assert window.to_date == date(2026, 8, 5)
        assert window.from_date == date(2026, 7, 7)
        assert (window.to_date - window.from_date).days == 29

    def test_today_defaults_to_the_real_clock(self) -> None:
        window = resolve_window(None, None)

        assert window.to_date == datetime.now(UTC).date()

    def test_only_from_given_runs_through_today(self) -> None:
        window = resolve_window(date(2026, 8, 1), None, today=date(2026, 8, 5))

        assert (window.from_date, window.to_date) == (date(2026, 8, 1), date(2026, 8, 5))

    def test_from_after_to_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            resolve_window(date(2026, 8, 5), date(2026, 8, 1))

    def test_the_previous_window_has_the_same_length_and_ends_at_start(self) -> None:
        window = resolve_window(date(2026, 7, 11), date(2026, 7, 20))

        prev_start, prev_end = window.previous
        assert prev_end == window.start
        assert prev_end - prev_start == window.end - window.start
        assert prev_start == datetime(2026, 7, 1, tzinfo=UTC)


class TestTheScopeDecision:
    async def test_org_scope_without_runs_view_is_refused(self, repos) -> None:
        service = StatsService(MagicMock())

        with pytest.raises(AuthorizationError):
            await service.usage(_ctx(role=OrgRoleName.MEMBER.value), scope="org")

    async def test_own_scope_is_open_to_a_member_and_narrows_every_query(self, repos) -> None:
        ctx = _ctx(role=OrgRoleName.MEMBER.value)

        result = await StatsService(MagicMock()).usage(ctx, scope="own")

        assert result.scope == "own"
        for name in ("count_runs", "runs_by_day", "runs_by_dimension", "runs_by_agent"):
            for call in repos[name].call_args_list:
                assert call.kwargs["where"].user_id == ctx.user_id

    async def test_a_context_with_no_subject_cannot_ask_for_its_own_rows(self, repos) -> None:
        ctx = AuthContext.anonymous(uuid4())

        with pytest.raises(AuthorizationError):
            await StatsService(MagicMock()).usage(ctx, scope="own")

    async def test_org_scope_queries_are_not_narrowed_to_the_caller(self, repos) -> None:
        await StatsService(MagicMock()).usage(_ctx(), scope="org")

        for call in repos["count_runs"].call_args_list:
            assert call.kwargs["where"].user_id is None


class TestTheComposedAnswer:
    async def test_days_with_no_runs_are_present_with_zero(self, repos) -> None:
        repos["runs_by_day"].return_value = [(date(2026, 7, 2), 5, 4, Decimal("1.25"))]

        result = await StatsService(MagicMock()).usage(
            _ctx(), from_date=date(2026, 7, 1), to_date=date(2026, 7, 3)
        )

        assert result.by_day is not None
        assert [(entry.date, entry.runs) for entry in result.by_day] == [
            (date(2026, 7, 1), 0),
            (date(2026, 7, 2), 5),
            (date(2026, 7, 3), 0),
        ]

    async def test_a_day_carries_what_completed_and_what_it_cost(self, repos) -> None:
        # Three measures from one scan, so a figure's sparkline is free rather
        # than three more round trips.
        repos["runs_by_day"].return_value = [(date(2026, 7, 2), 5, 4, Decimal("1.25"))]

        result = await StatsService(MagicMock()).usage(
            _ctx(), from_date=date(2026, 7, 1), to_date=date(2026, 7, 2)
        )

        assert result.by_day is not None
        empty, busy = result.by_day
        assert (empty.runs, empty.completed, empty.cost_usd) == (0, 0, Decimal(0))
        assert (busy.runs, busy.completed, busy.cost_usd) == (5, 4, Decimal("1.25"))

    async def test_the_window_costs_models_plus_ingestion(self, repos) -> None:
        # The defect this fixes: the headline was models alone while the
        # month-to-date line beside it was the whole bill, and nothing on the
        # card said they were different questions.
        repos["sum_cost_window"].side_effect = [Decimal("2.00"), Decimal("1.00")]
        repos["ingestion_sum_cost_window"].side_effect = [Decimal("0.50"), Decimal("0.25")]

        result = await StatsService(MagicMock()).usage(_ctx())

        assert result.cost is not None
        assert result.cost.model_usd == Decimal("2.00")
        assert result.cost.ingestion_usd == Decimal("0.50")
        assert result.cost.period_usd == Decimal("2.50")
        # The previous window is the whole bill too, or the change compares a
        # bill against half of one.
        assert result.cost.previous_period_usd == Decimal("1.25")

    async def test_own_scope_is_not_billed_for_the_organizations_indexing(self, repos) -> None:
        # `ingestion_spend` records no user - a document is indexed by a worker -
        # so charging a member's own window for a collection somebody else
        # synced would be inventing their spend.
        repos["sum_cost_window"].return_value = Decimal("2.00")

        result = await StatsService(MagicMock()).usage(_ctx(), scope="own")

        assert result.cost is not None
        assert result.cost.ingestion_usd == Decimal(0)
        assert result.cost.period_usd == Decimal("2.00")
        repos["ingestion_sum_cost_window"].assert_not_called()

    async def test_the_previous_total_is_asked_of_the_previous_window(self, repos) -> None:
        repos["count_runs"].side_effect = [40, 31]

        result = await StatsService(MagicMock()).usage(
            _ctx(), from_date=date(2026, 7, 11), to_date=date(2026, 7, 20)
        )

        assert (result.total_runs, result.previous_total_runs) == (40, 31)
        previous_call = repos["count_runs"].call_args_list[1]
        assert previous_call.kwargs["start"] == datetime(2026, 7, 1, tzinfo=UTC)
        assert previous_call.kwargs["end"] == datetime(2026, 7, 11, tzinfo=UTC)

    async def test_latency_is_rounded_to_whole_milliseconds(self, repos) -> None:
        repos["latency_percentiles_ms"].return_value = (3200.4, 14800.6)

        result = await StatsService(MagicMock()).usage(_ctx())

        assert result.latency_ms is not None
        assert (result.latency_ms.p50, result.latency_ms.p95) == (3200, 14801)

    async def test_an_empty_window_answers_zeros_and_null_latency(self, repos) -> None:
        result = await StatsService(MagicMock()).usage(
            _ctx(), from_date=date(2026, 7, 1), to_date=date(2026, 7, 1)
        )

        assert result.total_runs == 0
        assert result.latency_ms is not None
        assert (result.latency_ms.p50, result.latency_ms.p95) == (None, None)
        assert result.cost is not None
        assert result.cost.period_usd == Decimal(0)

    async def test_org_scope_carries_active_users_and_no_approvals_count(self, repos) -> None:
        repos["count_distinct_users"].return_value = 14
        repos["count_for_org"].return_value = 23

        result = await StatsService(MagicMock()).usage(_ctx(), scope="org")

        assert result.active_users is not None
        assert (result.active_users.active, result.active_users.total_members) == (14, 23)
        assert result.pending_approvals is None
        repos["count_pending_approval_runs"].assert_not_called()

    async def test_own_scope_carries_the_approvals_count_and_no_member_table(self, repos) -> None:
        repos["count_pending_approval_runs"].return_value = 2

        result = await StatsService(MagicMock()).usage(
            _ctx(role=OrgRoleName.MEMBER.value), scope="own"
        )

        assert result.pending_approvals == 2
        # The distinct-user count rides in the one window query now, so it is
        # computed either way; what a `user_id` scope drops is reporting it.
        assert result.active_users is None

    async def test_the_slices_map_through_with_their_names(self, repos) -> None:
        agent_id = uuid4()

        def by_dimension(db, *, dimension, **kwargs):
            return {
                "surface": [("web", 8), ("embed", 2)],
                "status": [("completed", 9), ("failed", 1)],
                "model": [("claude-sonnet-5", 7), (None, 3)],
            }[dimension]

        repos["runs_by_dimension"].side_effect = by_dimension
        repos["runs_by_agent"].return_value = [(agent_id, "Support triage", 10)]
        repos["cost_by_provider_window"].return_value = [("anthropic", Decimal("1.5"))]

        result = await StatsService(MagicMock()).usage(_ctx())

        assert result.by_surface is not None and result.by_surface[1].surface == "embed"
        assert result.by_status is not None and result.by_status[1].runs == 1
        assert result.by_model is not None and result.by_model[1].model_label is None
        assert result.by_agent is not None
        assert (result.by_agent[0].agent_id, result.by_agent[0].name) == (
            agent_id,
            "Support triage",
        )
        assert result.cost is not None and result.cost.by_provider[0].provider == "anthropic"

    async def test_the_response_serializes_from_and_to_by_alias(self, repos) -> None:
        result = await StatsService(MagicMock()).usage(
            _ctx(), from_date=date(2026, 7, 1), to_date=date(2026, 7, 3)
        )

        payload = result.model_dump(by_alias=True, mode="json")
        assert (payload["from"], payload["to"]) == ("2026-07-01", "2026-07-03")


class TestVersionGrouping:
    async def test_rows_carry_their_ratings_and_a_deleted_version_stays(self, repos) -> None:
        v3, v4 = uuid4(), uuid4()
        repos["usage_by_version"].return_value = [
            (None, None, 2, 1, None, None),
            (v3, 3, 10, 9, 16200.0, Decimal("0.048")),
            (v4, 4, 12, 12, 17100.4, Decimal("0.041")),
        ]
        repos["rating_counts_by_version"].return_value = {v3: (7, 8), v4: (11, 12)}

        result = await StatsService(MagicMock()).usage_by_version(_ctx(), agent_id=uuid4())

        assert result.by_version is not None
        deleted, old, new = result.by_version
        assert (deleted.agent_version_id, deleted.version) == (None, None)
        assert (deleted.like_count, deleted.rating_count) == (0, 0)
        assert (old.version, old.runs, old.completed_runs) == (3, 10, 9)
        assert (old.like_count, old.rating_count) == (7, 8)
        assert new.p95_ms == 17100
        assert new.avg_cost_usd == Decimal("0.041")

    async def test_the_envelope_names_the_agent_and_skips_the_composed_blocks(self, repos) -> None:
        agent_id = uuid4()

        result = await StatsService(MagicMock()).usage_by_version(_ctx(), agent_id=agent_id)

        assert result.agent_id == agent_id
        assert result.by_version == []
        assert result.total_runs is None
        assert result.by_day is None
        repos["count_runs"].assert_not_called()

    async def test_no_versions_means_no_ratings_query(self, repos) -> None:
        repos["usage_by_version"].return_value = [(None, None, 2, 2, None, None)]

        await StatsService(MagicMock()).usage_by_version(_ctx(), agent_id=uuid4())

        repos["rating_counts_by_version"].assert_not_called()

    async def test_own_scope_narrows_the_version_rows_to_the_caller(self, repos) -> None:
        ctx = _ctx(role=OrgRoleName.MEMBER.value)

        await StatsService(MagicMock()).usage_by_version(ctx, agent_id=uuid4(), scope="own")

        assert repos["usage_by_version"].call_args.kwargs["where"].user_id == ctx.user_id

    async def test_org_scope_still_demands_runs_view(self, repos) -> None:
        with pytest.raises(AuthorizationError):
            await StatsService(MagicMock()).usage_by_version(
                _ctx(role=OrgRoleName.MEMBER.value), agent_id=uuid4(), scope="org"
            )


class TestHourGrouping:
    async def test_cells_carry_the_weekday_and_hour_the_database_answered(self, repos) -> None:
        repos["runs_by_hour"].return_value = [(0, 9, 4), (3, 14, 11)]

        result = await StatsService(MagicMock()).usage_by_hour(_ctx())

        assert result.by_hour is not None
        assert [(cell.weekday, cell.hour, cell.runs) for cell in result.by_hour] == [
            (0, 9, 4),
            (3, 14, 11),
        ]

    async def test_the_envelope_skips_the_composed_blocks(self, repos) -> None:
        # A different question about the same window: computing eight answers
        # nobody asked for would be waste dressed as consistency.
        result = await StatsService(MagicMock()).usage_by_hour(_ctx())

        assert result.total_runs is None
        assert result.by_day is None
        assert result.cost is None

    async def test_own_scope_narrows_the_cells_to_the_caller(self, repos) -> None:
        ctx = _ctx(role=OrgRoleName.MEMBER.value)

        await StatsService(MagicMock()).usage_by_hour(ctx, scope="own")

        assert repos["runs_by_hour"].await_args.kwargs["where"].user_id == ctx.user_id

    async def test_org_scope_still_demands_runs_view(self, repos) -> None:
        with pytest.raises(AuthorizationError):
            await StatsService(MagicMock()).usage_by_hour(_ctx(role=OrgRoleName.MEMBER.value))


class TestPersonGrouping:
    async def test_rows_carry_the_person_and_what_they_cost(self, repos) -> None:
        first, second = uuid4(), uuid4()
        repos["usage_by_user"].return_value = [
            (first, "k.nowak@example.com", "Katarzyna Nowak", 381, Decimal("15.60"), _AT),
            (second, "j.wisniewski@example.com", None, 300, Decimal("12.32"), _AT),
        ]

        result = await StatsService(MagicMock()).usage_by_user(_ctx(), limit=10)

        assert result.by_user is not None
        busiest, next_one = result.by_user
        assert (busiest.user_id, busiest.email) == (first, "k.nowak@example.com")
        assert (busiest.runs, busiest.cost_usd) == (381, Decimal("15.60"))
        assert busiest.full_name == "Katarzyna Nowak"
        assert next_one.full_name is None
        assert next_one.last_run_at == _AT

    async def test_the_envelope_skips_the_composed_blocks(self, repos) -> None:
        result = await StatsService(MagicMock()).usage_by_user(_ctx(), limit=10)

        assert result.by_user == []
        assert result.total_runs is None
        assert result.active_users is None
        repos["count_runs"].assert_not_called()

    async def test_the_limit_reaches_the_repository(self, repos) -> None:
        await StatsService(MagicMock()).usage_by_user(_ctx(), limit=6)

        assert repos["usage_by_user"].call_args.kwargs["limit"] == 6

    async def test_own_scope_narrows_the_table_to_the_callers_own_row(self, repos) -> None:
        ctx = _ctx(role=OrgRoleName.MEMBER.value)

        await StatsService(MagicMock()).usage_by_user(ctx, scope="own", limit=10)

        assert repos["usage_by_user"].call_args.kwargs["where"].user_id == ctx.user_id

    async def test_naming_the_organizations_people_demands_runs_view(self, repos) -> None:
        """The card names people, so the refusal matters more here than anywhere."""
        with pytest.raises(AuthorizationError):
            await StatsService(MagicMock()).usage_by_user(
                _ctx(role=OrgRoleName.MEMBER.value), scope="org", limit=10
            )


class TestRatingsSummary:
    async def test_org_scope_reads_the_whole_organization(self, repos) -> None:
        ctx = _ctx()
        repos["get_rating_summary_scoped"].return_value = {
            "total_ratings": 214,
            "like_count": 195,
            "dislike_count": 19,
            "average_rating": 0.82,
            "with_comments": 12,
            "ratings_by_day": [{"date": "2026-07-01", "likes": 10, "dislikes": 1}],
        }

        result = await StatsService(MagicMock()).ratings_summary(
            ctx, from_date=date(2026, 7, 1), to_date=date(2026, 7, 31)
        )

        call = repos["get_rating_summary_scoped"].call_args
        assert call.kwargs["organization_id"] == ctx.organization_id
        assert call.kwargs["user_id"] is None
        assert (result.total_ratings, result.like_count) == (214, 195)
        assert result.scope == "org"
        payload = result.model_dump(by_alias=True, mode="json")
        assert (payload["from"], payload["to"]) == ("2026-07-01", "2026-07-31")

    async def test_own_scope_narrows_to_the_callers_conversations(self, repos) -> None:
        ctx = _ctx(role=OrgRoleName.MEMBER.value)

        result = await StatsService(MagicMock()).ratings_summary(ctx, scope="own")

        assert repos["get_rating_summary_scoped"].call_args.kwargs["user_id"] == ctx.user_id
        assert result.scope == "own"

    async def test_org_scope_demands_runs_view_here_too(self, repos) -> None:
        with pytest.raises(AuthorizationError):
            await StatsService(MagicMock()).ratings_summary(
                _ctx(role=OrgRoleName.VIEWER.value), scope="org"
            )


class TestNarrowingOneCard:
    """A dashboard card may ask about one agent, or one colleague, or both.

    The page carries one window and one organization; these are what let a card
    beside it ask a narrower question, so what matters is that the narrowing
    reaches *every* aggregate rather than the two the first card happened to
    read - and that a filtered window stops claiming costs it cannot attribute.
    """

    async def test_an_agent_filter_reaches_every_aggregate(self, repos) -> None:
        agent_id = uuid4()

        await StatsService(MagicMock()).usage(_ctx(), agent_id=agent_id)

        for name in (
            "count_runs",
            "runs_by_day",
            "runs_by_dimension",
            "runs_by_agent",
            "latency_percentiles_ms",
            "sum_cost_window",
            "cost_by_provider_window",
            "count_distinct_users",
        ):
            assert repos[name].call_args_list, name
            for call in repos[name].call_args_list:
                assert call.kwargs["where"].agent_id == agent_id, name

    async def test_a_person_filter_narrows_org_scope_to_that_person(self, repos) -> None:
        someone = uuid4()

        await StatsService(MagicMock()).usage(_ctx(), user_id=someone)

        for call in repos["count_runs"].call_args_list:
            assert call.kwargs["where"].user_id == someone

    async def test_a_narrowed_window_reports_no_ingestion(self, repos) -> None:
        # Indexing is the organization's bill: `ingestion_spend` records neither
        # an agent nor a person, so a narrowed card that added it would present
        # somebody else's collection sync as this agent's cost.
        repos["ingestion_sum_cost_window"].return_value = Decimal("4.00")

        result = await StatsService(MagicMock()).usage(_ctx(), agent_id=uuid4())

        assert result.cost is not None
        assert result.cost.ingestion_usd == Decimal(0)
        repos["ingestion_sum_cost_window"].assert_not_awaited()

    async def test_the_whole_window_still_reports_ingestion(self, repos) -> None:
        repos["ingestion_sum_cost_window"].return_value = Decimal("4.00")

        result = await StatsService(MagicMock()).usage(_ctx())

        assert result.cost is not None
        assert result.cost.ingestion_usd == Decimal("4.00")

    async def test_own_scope_refuses_a_user_id_rather_than_reinterpreting_it(self, repos) -> None:
        # It could only ever be the caller's own, so a request naming somebody
        # is a mistake - answered, not silently rewritten into "yourself".
        with pytest.raises(ValidationError):
            await StatsService(MagicMock()).usage(_ctx(), scope="own", user_id=uuid4())

    async def test_an_agent_filter_reaches_the_hourly_grid(self, repos) -> None:
        agent_id = uuid4()

        await StatsService(MagicMock()).usage_by_hour(_ctx(), agent_id=agent_id)

        assert repos["runs_by_hour"].await_args.kwargs["where"].agent_id == agent_id

    async def test_an_agent_filter_reaches_the_per_person_table(self, repos) -> None:
        agent_id = uuid4()

        await StatsService(MagicMock()).usage_by_user(_ctx(), limit=5, agent_id=agent_id)

        assert repos["usage_by_user"].call_args.kwargs["where"].agent_id == agent_id
