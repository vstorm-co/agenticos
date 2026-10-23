"""Watches: the proactive look pointed at a person's own connections (#2301).

What is asserted is what a person or their organization would notice: a watch
is only set up where the organization allows it, on the person's own
connection, no more often than allowed; a look offers the model nothing that
writes, reports each item once, and sends at once only what both the person and
the model call urgent; and a watch the organization stopped is not read.
"""

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError as PydanticValidationError
from pydantic_ai.tools import ToolDefinition

from app.api.deps import get_auth_context, get_watch_service
from app.core.exceptions import AuthenticationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.watch import Watch
from app.main import app
from app.schemas.watch import WatchCreate, WatchRead, WatchUpdate
from app.services import mcp_catalog, watch_presets
from app.services.proactive._watch import (
    Found,
    WatchLook,
    WatchReading,
    _key,
    _reads_only,
    _web_link,
)
from app.services.proactive.facade import ProactiveService
from app.services.watches import MAX_WATCHES, WatchService, stopped_by, watch_read
from app.worker.jobs import LOOK_THROUGH_WATCH
from app.worker.tasks import proactive_tasks

pytestmark = pytest.mark.anyio

SERVICE = "app.services.watches"
LOOK = "app.services.proactive._watch"
FACADE = "app.services.proactive.facade"

ORG = uuid.uuid4()
USER = uuid.uuid4()
NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)


def _ctx(user_id: uuid.UUID | None = USER) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=ORG, role=OrgRoleName.MEMBER)


def _organization(*, on: bool = True, floor: int = 60) -> MagicMock:
    return MagicMock(id=ORG, proactive_watches_enabled=on, proactive_watch_min_minutes=floor)


def _connection(
    *,
    owner: uuid.UUID = USER,
    server: str | None = "github",
    scope: str = "user",
    purpose: str = "mcp",
    enabled: bool = True,
) -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        scope=scope,
        purpose=purpose,
        user_id=owner,
        catalog_key=server,
        is_enabled=enabled,
        label=None,
        url="https://mcp.example/github",
        allowed_tools=None,
        include_instructions=False,
    )
    # `name` is a MagicMock constructor argument, so it is set after.


def _named(connection: MagicMock, name: str = "GitHub") -> MagicMock:
    connection.name = name
    return connection


def _watch(**overrides: object) -> Watch:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": ORG,
        "user_id": USER,
        "connection_id": uuid.uuid4(),
        "preset_key": None,
        "title": "Reviews",
        "instructions": "Pull requests waiting on my review.",
        "exclusions": [],
        "urgent": False,
        "interval_minutes": 60,
        "is_active": True,
        "next_run_at": NOW,
        "last_run_at": None,
        "created_at": NOW,
    }
    return Watch(**(fields | overrides))


def _create(**overrides: object) -> WatchCreate:
    fields: dict[str, object] = {
        "connection_id": uuid.uuid4(),
        "title": "Reviews",
        "instructions": "Pull requests waiting on my review.",
        "interval_minutes": 60,
    }
    return WatchCreate.model_validate(fields | overrides)


class TestPresets:
    def test_every_preset_is_for_a_server_in_the_catalog(self):
        assert {preset.catalog_key for preset in watch_presets.PRESETS} <= set(mcp_catalog.BY_KEY)

    def test_keys_are_unique_and_no_preset_is_read_more_often_than_any_watch_may_be(self):
        keys = [preset.key for preset in watch_presets.PRESETS]
        assert len(keys) == len(set(keys))
        assert all(preset.interval_minutes >= 15 for preset in watch_presets.PRESETS)

    def test_the_service_offers_every_preset(self):
        assert WatchService.presets() == list(watch_presets.PRESETS)

    def test_a_server_gets_its_own_presets_and_a_custom_one_none(self):
        assert {preset.catalog_key for preset in watch_presets.for_server("github")} == {"github"}
        assert watch_presets.for_server(None) == ()


class TestWhatStopsAWatch:
    @pytest.mark.parametrize(
        ("organization", "connection", "stopped"),
        [
            (_organization(on=False), _connection(), "watches_off"),
            (_organization(), _connection(enabled=False), "connection_disabled"),
            (_organization(), _connection(), None),
            (_organization(), _connection(server=None), None),
        ],
        ids=["off", "disabled", "catalog-server", "custom-server"],
    )
    def test_the_organizations_rules_and_the_connection(self, organization, connection, stopped):
        assert stopped_by(organization, connection) == stopped

    def test_a_read_names_the_connection_as_its_person_calls_it(self):
        connection = _named(_connection())
        connection.label = "Work"
        read = watch_read(_watch(), organization=_organization(), connection=connection)
        assert read.connection_name == "Work"
        assert read.server == "github"
        assert read.stopped is None


class TestSettingOneUp:
    @staticmethod
    def _patches(organization, connection, *, mine=0):
        create = AsyncMock(side_effect=lambda _db, **kwargs: _watch(**kwargs))
        return create, (
            patch(
                f"{SERVICE}.organization_repo.get_by_id", new=AsyncMock(return_value=organization)
            ),
            patch(
                f"{SERVICE}.mcp_connection_repo.get_by_id", new=AsyncMock(return_value=connection)
            ),
            patch(
                f"{SERVICE}.watch_repo.list_own",
                new=AsyncMock(return_value=[_watch() for _ in range(mine)]),
            ),
            patch(f"{SERVICE}.watch_repo.create", new=create),
        )

    async def test_a_watch_on_ones_own_connection_is_read_within_a_minute(self):
        connection = _named(_connection())
        create, patches = self._patches(_organization(), connection)
        with patches[0], patches[1], patches[2], patches[3]:
            read = await WatchService(MagicMock()).create(
                _ctx(), _create(connection_id=connection.id, preset_key="github-reviews")
            )

        assert isinstance(read, WatchRead)
        kwargs = create.await_args.kwargs
        assert kwargs["user_id"] == USER and kwargs["preset_key"] == "github-reviews"
        assert datetime.now(UTC) - kwargs["next_run_at"] < timedelta(minutes=1)

    @pytest.mark.parametrize(
        ("organization", "connection", "data", "field"),
        [
            (_organization(on=False), _connection(), {}, None),
            (_organization(floor=120), _connection(), {"interval_minutes": 60}, "interval_minutes"),
            (_organization(), _connection(), {"preset_key": "linear-assigned"}, "preset_key"),
            (_organization(), _connection(), {"preset_key": "nothing-like-it"}, "preset_key"),
            (_organization(), _connection(owner=uuid.uuid4()), {}, "connection_id"),
            (_organization(), _connection(scope="org"), {}, "connection_id"),
            (_organization(), _connection(purpose="portal"), {}, "connection_id"),
            (_organization(), None, {}, "connection_id"),
        ],
        ids=[
            "watches-off",
            "too-often",
            "preset-for-another-server",
            "unknown-preset",
            "somebody-elses-connection",
            "an-organization-connection",
            "a-trigger-grant",
            "no-such-connection",
        ],
    )
    async def test_what_the_organization_or_the_person_does_not_allow_is_refused(
        self, organization, connection, data, field
    ):
        create, patches = self._patches(organization, connection)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            pytest.raises(BadRequestError) as refused,
        ):
            await WatchService(MagicMock()).create(_ctx(), _create(**data))

        create.assert_not_awaited()
        named = [problem["field"] for problem in (refused.value.details or {}).get("fields", [])]
        assert named == ([] if field is None else [field])

    async def test_a_person_has_at_most_so_many(self):
        create, patches = self._patches(_organization(), _named(_connection()), mine=MAX_WATCHES)
        with patches[0], patches[1], patches[2], patches[3], pytest.raises(BadRequestError):
            await WatchService(MagicMock()).create(_ctx(), _create())
        create.assert_not_awaited()

    async def test_nobody_signed_in_has_watches(self):
        with pytest.raises(AuthenticationError):
            await WatchService(MagicMock()).list_mine(_ctx(user_id=None))

    async def test_an_organization_that_is_gone_is_not_found(self):
        with (
            patch(f"{SERVICE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await WatchService(MagicMock()).list_mine(_ctx())


class TestChangingOne:
    @staticmethod
    def _patches(watch, organization, connection):
        update = AsyncMock(
            side_effect=lambda _db, *, watch, changes: _watch(
                **{
                    "id": watch.id,
                    "connection_id": watch.connection_id,
                    "is_active": watch.is_active,
                    **changes,
                }
            )
        )
        return update, (
            patch(
                f"{SERVICE}.organization_repo.get_by_id", new=AsyncMock(return_value=organization)
            ),
            patch(f"{SERVICE}.watch_repo.get_own", new=AsyncMock(return_value=watch)),
            patch(f"{SERVICE}.watch_repo.update_fields", new=update),
            patch(
                f"{SERVICE}.mcp_connection_repo.get_by_id", new=AsyncMock(return_value=connection)
            ),
        )

    async def test_switched_back_on_it_looks_soon_and_takes_what_is_left_out(self):
        watch = _watch(is_active=False, next_run_at=NOW - timedelta(days=30))
        update, patches = self._patches(watch, _organization(), _named(_connection()))
        with patches[0], patches[1], patches[2], patches[3]:
            read = await WatchService(MagicMock()).update(
                _ctx(),
                watch.id,
                WatchUpdate(is_active=True, exclusions=[" dependabot ", "", "dependabot"]),
            )

        changes = update.await_args.kwargs["changes"]
        assert changes["exclusions"] == ["dependabot"]
        assert datetime.now(UTC) - changes["next_run_at"] < timedelta(minutes=1)
        assert read.exclusions == ["dependabot"]

    async def test_a_pause_keeps_its_time_and_a_new_cadence_must_be_allowed(self):
        watch = _watch()
        update, patches = self._patches(watch, _organization(floor=240), _named(_connection()))
        with patches[0], patches[1], patches[2], patches[3]:
            await WatchService(MagicMock()).update(_ctx(), watch.id, WatchUpdate(is_active=False))
            assert "next_run_at" not in update.await_args.kwargs["changes"]
            with pytest.raises(BadRequestError):
                await WatchService(MagicMock()).update(
                    _ctx(), watch.id, WatchUpdate(interval_minutes=60)
                )

    async def test_somebody_elses_watch_is_not_found_and_deleting_ones_own_removes_it(self):
        watch = _watch()
        delete = AsyncMock()
        with (
            patch(f"{SERVICE}.watch_repo.get_own", new=AsyncMock(side_effect=[None, watch])),
            patch(f"{SERVICE}.watch_repo.delete", new=delete),
        ):
            with pytest.raises(NotFoundError):
                await WatchService(MagicMock()).delete(_ctx(), uuid.uuid4())
            await WatchService(MagicMock()).delete(_ctx(), watch.id)

        delete.assert_awaited_once()
        assert delete.await_args.args[1] is watch

    def test_null_and_overlong_lines_are_refused_at_the_schema(self):
        for null in ({"title": None}, {"exclusions": None}):
            with pytest.raises(PydanticValidationError):
                WatchUpdate.model_validate(null)
        with pytest.raises(PydanticValidationError):
            WatchUpdate.model_validate({"exclusions": ["x" * 201]})


class TestListingThem:
    async def test_each_says_why_it_is_not_read_and_one_whose_connection_went_is_left_out(self):
        kept, orphan = _watch(), _watch()
        connection = _named(_connection(enabled=False))
        with (
            patch(
                f"{SERVICE}.organization_repo.get_by_id",
                new=AsyncMock(return_value=_organization()),
            ),
            patch(f"{SERVICE}.watch_repo.list_own", new=AsyncMock(return_value=[kept, orphan])),
            patch(
                f"{SERVICE}.mcp_connection_repo.get_by_id",
                new=AsyncMock(side_effect=[connection, None]),
            ),
            patch(
                f"{SERVICE}.suggestion_repo.open_findings_by_watch",
                new=AsyncMock(return_value={kept.id: 3}),
            ) as waiting,
        ):
            reads = await WatchService(MagicMock()).list_mine(_ctx())

        assert waiting.await_args.kwargs["watch_ids"] == [kept.id, orphan.id]
        assert [read.id for read in reads] == [kept.id]
        assert reads[0].stopped == "connection_disabled"
        assert reads[0].waiting == 3


class TestOneLook:
    def test_only_tools_the_server_marks_read_only_are_offered(self):
        reads = ToolDefinition(name="list", metadata={"annotations": {"readOnlyHint": True}})
        silent = ToolDefinition(name="send")
        writes = ToolDefinition(name="delete", metadata={"annotations": {"readOnlyHint": False}})
        ctx = MagicMock()
        assert [_reads_only(ctx, tool) for tool in (reads, silent, writes)] == [True, False, False]

    @pytest.mark.parametrize(
        ("url", "kept"),
        [
            ("https://github.com/o/r/pull/1", True),
            ("http://intranet.example/x", True),
            ("javascript:alert(1)", False),
            ("https:///no-host", False),
            (None, False),
        ],
    )
    def test_a_link_is_kept_only_where_a_browser_opens_it(self, url, kept):
        assert (_web_link(url) is not None) is kept

    def test_the_same_item_has_the_same_key_and_another_watch_another(self):
        one, other = uuid.uuid4(), uuid.uuid4()
        assert _key(one, "PR 12") == _key(one, " PR 12 ")
        assert _key(one, "PR 12") != _key(other, "PR 12")
        assert len(_key(one, "PR 12")) <= 64

    @staticmethod
    def _patches(watch, *, organization=None, connection=None, member=True, user=True, spec=True):
        person = MagicMock(id=USER, is_active=True, locale="pl", time_zone="Europe/Warsaw")
        found_spec = MagicMock(account="kacper")
        return (
            patch(f"{LOOK}.watch_repo.get_by_id", new=AsyncMock(return_value=watch)),
            patch(
                f"{LOOK}.organization_repo.get_by_id",
                new=AsyncMock(return_value=organization or _organization()),
            ),
            patch(
                f"{LOOK}.mcp_connection_repo.get_by_id",
                new=AsyncMock(return_value=connection or _named(_connection())),
            ),
            patch(
                f"{LOOK}.member_repo.get_active",
                new=AsyncMock(return_value=MagicMock(role="member") if member else None),
            ),
            patch(
                f"{LOOK}.user_repo.get_by_id", new=AsyncMock(return_value=person if user else None)
            ),
            patch(
                f"{LOOK}.watched_connection_spec",
                new=AsyncMock(return_value=found_spec if spec else None),
            ),
        )

    async def test_findings_are_recorded_once_and_only_the_urgent_are_sent_at_once(self):
        watch = _watch(urgent=True, exclusions=["dependabot"])
        reading = WatchReading(
            findings=[
                Found(key="1", title="Review #1", url="https://github.com/o/r/pull/1", urgent=True),
                Found(key="2", title="Review #2", url="javascript:void(0)"),
                Found(key="3", title="Seen before", urgent=True),
            ]
        )
        toolset = MagicMock()
        proposed = [MagicMock(id=uuid.uuid4(), title="Review #1"), MagicMock(), None]
        propose = AsyncMock(side_effect=proposed)
        think = AsyncMock(return_value=reading)
        finding = AsyncMock()
        with ExitStack() as stack:
            for each in (
                *self._patches(watch),
                patch(f"{LOOK}.build_mcp_toolsets", new=AsyncMock(return_value=[toolset])),
                patch(
                    f"{LOOK}.suggestion_repo.titles_for_watch",
                    new=AsyncMock(return_value=["Old"]),
                ),
                patch(f"{LOOK}.suggestion_repo.propose", new=propose),
                patch(f"{LOOK}.NotificationService", return_value=MagicMock(finding=finding)),
                patch(f"{LOOK}.ProactiveThinker", return_value=MagicMock(think=think)),
            ):
                stack.enter_context(each)
            mark_ran = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock()))
            assert await WatchLook(MagicMock()).look(watch.id) == 2

        kwargs = think.await_args.kwargs
        assert kwargs["feature"] == "watches"
        assert kwargs["toolsets"] == [toolset.filtered.return_value]
        toolset.filtered.assert_called_once_with(_reads_only)
        assert '"not_wanted": ["dependabot"]' in kwargs["prompt"]
        assert '"already_reported": ["Old"]' in kwargs["prompt"]
        first, second, _ = (call.kwargs for call in propose.await_args_list)
        assert first["urgent"] is True and first["payload"]["url"].startswith("https://")
        assert second["urgent"] is False and second["payload"]["url"] is None
        assert first["payload"]["server"] == "github" and first["payload"]["account"] == "kacper"
        finding.assert_awaited_once()
        assert finding.await_args.kwargs["title"] == "Review #1"
        mark_ran.assert_awaited_once()

    async def test_a_watch_that_does_not_ask_for_it_never_sends_at_once(self):
        watch = _watch(urgent=False)
        reading = WatchReading(findings=[Found(key="1", title="Invoice overdue", urgent=True)])
        propose = AsyncMock(return_value=MagicMock(id=uuid.uuid4(), title="Invoice overdue"))
        finding = AsyncMock()
        with ExitStack() as stack:
            for each in (
                *self._patches(watch),
                patch(f"{LOOK}.build_mcp_toolsets", new=AsyncMock(return_value=[MagicMock()])),
                patch(f"{LOOK}.suggestion_repo.titles_for_watch", new=AsyncMock(return_value=[])),
                patch(f"{LOOK}.suggestion_repo.propose", new=propose),
                patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock()),
                patch(f"{LOOK}.NotificationService", return_value=MagicMock(finding=finding)),
                patch(
                    f"{LOOK}.ProactiveThinker",
                    return_value=MagicMock(think=AsyncMock(return_value=reading)),
                ),
            ):
                stack.enter_context(each)
            assert await WatchLook(MagicMock()).look(watch.id) == 1

        assert propose.await_args.kwargs["urgent"] is False
        finding.assert_not_awaited()

    async def test_a_model_that_could_not_answer_records_the_look_and_nothing_else(self):
        watch = _watch()
        propose = AsyncMock()
        with ExitStack() as stack:
            for each in (
                *self._patches(watch),
                patch(f"{LOOK}.build_mcp_toolsets", new=AsyncMock(return_value=[MagicMock()])),
                patch(f"{LOOK}.suggestion_repo.titles_for_watch", new=AsyncMock(return_value=[])),
                patch(f"{LOOK}.suggestion_repo.propose", new=propose),
                patch(
                    f"{LOOK}.ProactiveThinker",
                    return_value=MagicMock(think=AsyncMock(return_value=None)),
                ),
            ):
                stack.enter_context(each)
            mark_ran = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock()))
            assert await WatchLook(MagicMock()).look(watch.id) == 0
        mark_ran.assert_awaited_once()
        propose.assert_not_awaited()

    @pytest.mark.parametrize(
        "case",
        [
            "gone",
            "paused",
            "watches-off",
            "left-the-organization",
            "no-account",
            "credential-dead",
            "server-down",
        ],
    )
    async def test_nothing_is_read_where_it_should_not_be(self, case):
        watch = None if case == "gone" else _watch(is_active=case != "paused")
        organization = {
            "watches-off": _organization(on=False),
        }.get(case)
        think = AsyncMock()
        with ExitStack() as stack:
            for each in (
                *self._patches(
                    watch,
                    organization=organization,
                    member=case != "left-the-organization",
                    user=case != "no-account",
                    spec=case != "credential-dead",
                ),
                patch(f"{LOOK}.build_mcp_toolsets", new=AsyncMock(return_value=[])),
                patch(f"{LOOK}.ProactiveThinker", return_value=MagicMock(think=think)),
            ):
                stack.enter_context(each)
            assert await WatchLook(MagicMock()).look(uuid.uuid4()) == 0
        think.assert_not_awaited()


class TestTheSweep:
    async def test_each_due_watch_moves_on_by_the_larger_of_its_cadence_and_the_floor(self):
        quick = _watch(interval_minutes=15)
        slow = _watch(interval_minutes=240)
        stopped = _watch(organization_id=uuid.uuid4())
        orphan = _watch(organization_id=uuid.uuid4())
        organizations = {
            ORG: _organization(floor=60),
            stopped.organization_id: _organization(on=False),
            orphan.organization_id: None,
        }
        schedule = AsyncMock()
        get_organization = AsyncMock(side_effect=lambda _db, org_id: organizations[org_id])
        with (
            patch(
                f"{LOOK}.watch_repo.claim_due",
                new=AsyncMock(return_value=[quick, slow, stopped, orphan]),
            ),
            patch(f"{LOOK}.watch_repo.schedule", new=schedule),
            patch(f"{LOOK}.organization_repo.get_by_id", new=get_organization),
        ):
            due = await WatchLook(MagicMock()).due(now=NOW)

        assert due == [quick, slow]
        moved = {
            call.kwargs["watch_id"]: call.kwargs["next_run_at"] for call in schedule.await_args_list
        }
        assert moved[quick.id] == NOW + timedelta(minutes=60)
        assert moved[slow.id] == NOW + timedelta(minutes=240)
        assert moved[stopped.id] == NOW + timedelta(minutes=60)
        assert moved[orphan.id] == NOW + timedelta(minutes=60)
        # One organization read once, however many of its watches are due.
        assert get_organization.await_count == 3

    async def test_the_facade_queues_a_look_per_due_watch_and_the_worker_hands_them_on(self):
        watch = _watch()
        enqueue = AsyncMock()
        with (
            patch.object(WatchLook, "due", new=AsyncMock(return_value=[watch])),
            patch.object(WatchLook, "look", new=AsyncMock(return_value=3)),
            patch(f"{FACADE}.enqueue", new=enqueue),
        ):
            service = ProactiveService(MagicMock())
            assert await service.sweep_watches(now=NOW) == 1
            assert await service.look_through(watch.id) == 3

        (_, task, payload) = enqueue.await_args.args
        assert task is LOOK_THROUGH_WATCH and payload.watch_id == watch.id
        assert enqueue.await_args.kwargs["organization_id"] == ORG
        assert enqueue.await_args.kwargs["dedupe_key"] == f"watch:{watch.id}"

    async def test_the_worker_tasks_open_a_session_each(self):
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=MagicMock())
        context.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(proactive_tasks, "get_db_context", return_value=context),
            patch.object(ProactiveService, "sweep_watches", new=AsyncMock(return_value=2)),
            patch.object(ProactiveService, "look_through", new=AsyncMock(return_value=1)),
        ):
            assert await proactive_tasks.watch_sweep(MagicMock(scheduled_for=NOW)) == 2
            assert await proactive_tasks.look_through_watch(MagicMock(watch_id=uuid.uuid4())) == 1


class TestTheRoutes:
    @pytest.fixture
    def service(self):
        service = MagicMock()
        app.dependency_overrides[get_watch_service] = lambda: service
        app.dependency_overrides[get_auth_context] = _ctx
        yield service
        app.dependency_overrides.clear()

    async def test_set_up_list_change_and_remove(self, client: AsyncClient, service):
        read = watch_read(_watch(), organization=_organization(), connection=_named(_connection()))
        service.list_mine = AsyncMock(return_value=[read])
        service.create = AsyncMock(return_value=read)
        service.update = AsyncMock(return_value=read)
        service.delete = AsyncMock()
        service.presets = MagicMock(return_value=list(watch_presets.PRESETS))

        listed = await client.get("/api/v1/me/watches")
        presets = await client.get("/api/v1/me/watches/presets")
        made = await client.post(
            "/api/v1/me/watches",
            json={
                "connection_id": str(uuid.uuid4()),
                "title": "Reviews",
                "instructions": "Waiting on me.",
                "interval_minutes": 60,
            },
        )
        changed = await client.patch(f"/api/v1/me/watches/{read.id}", json={"urgent": True})
        removed = await client.delete(f"/api/v1/me/watches/{read.id}")

        assert listed.json()["total"] == 1
        assert presets.json()["total"] == len(watch_presets.PRESETS)
        assert {"key", "server", "instructions", "interval_minutes", "urgent"} <= set(
            presets.json()["items"][0]
        )
        assert made.status_code == 201 and changed.status_code == 200
        assert removed.status_code == 204

    async def test_a_cadence_more_often_than_any_watch_may_run_is_refused(
        self, client: AsyncClient, service
    ):
        response = await client.post(
            "/api/v1/me/watches",
            json={
                "connection_id": str(uuid.uuid4()),
                "title": "Too often",
                "instructions": "Everything.",
                "interval_minutes": 5,
            },
        )
        assert response.status_code == 422
