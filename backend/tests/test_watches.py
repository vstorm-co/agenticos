"""Watches: the proactive look pointed at a person's own connections (#2301).

What is asserted is what a person or their organization would notice: a watch
is only set up where the organization allows it, on the person's own
connection, no more often than allowed; a look offers the model nothing that
writes, reports each item once, and sends at once only what both the person and
the model call urgent; and a watch the organization stopped is not read.
"""

import hashlib
import uuid
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError as PydanticValidationError

from app.agents.spec import AgentSpec, PersonalMcpServerRef
from app.agents.watch_sources import WatchReadReceipt
from app.api.deps import get_auth_context, get_watch_service
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    RunFailedError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.watch import Watch, WatchAttemptStatus
from app.main import app
from app.schemas.watch import WatchCreate, WatchRead, WatchUpdate
from app.schemas.watch_sources import WatchSources
from app.services import mcp_catalog, watch_presets
from app.services.proactive._watch import (
    Found,
    WatchLook,
    WatchReading,
    _key,
    _web_link,
)
from app.services.proactive.facade import ProactiveService
from app.services.watch_sources import approve_sources
from app.services.watches import MAX_WATCHES, WatchService, stopped_by, watch_read
from app.worker.jobs import LOOK_THROUGH_WATCH
from app.worker.tasks import proactive_tasks

pytestmark = pytest.mark.anyio

SERVICE = "app.services.watches"
LOOK = "app.services.proactive._watch"
FACADE = "app.services.proactive.facade"

ORG = uuid.uuid4()
USER = uuid.uuid4()
AGENT = uuid.uuid4()
NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)


def _ctx(user_id: uuid.UUID | None = USER) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=ORG, role=OrgRoleName.MEMBER)


def _organization(*, on: bool = True, floor: int = 60) -> MagicMock:
    return MagicMock(
        id=ORG,
        proactive_watches_enabled=on,
        proactive_watch_min_minutes=floor,
        proactive_limit_usd=Decimal("1"),
    )


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
        authorization_generation=uuid.uuid4(),
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
        "report_mode": "changes",
        "notification_channels": None,
        "organization_id": ORG,
        "agent_id": AGENT,
        "approved_sources": WatchSources(
            connection_id=uuid.uuid4(),
            catalog_key="github",
            endpoint_hash=hashlib.sha256(b"https://mcp.example/github").hexdigest(),
        ).model_dump(mode="json"),
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
        "agent_id": AGENT,
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

    def test_the_mail_presets_are_offered_for_the_microsoft_365_server(self):
        mail = {preset.key for preset in watch_presets.for_server("ms-365")}
        assert {"mail-needs-reply", "mail-invoices", "mail-newsletters"} <= mail
        assert watch_presets.for_server("m365-mail") == ()

    def test_the_teams_preset_is_for_the_microsoft_365_server(self):
        """It reads chats and channels, which `ms-365` lists and `work-iq` caps and bills."""
        teams = next(p for p in watch_presets.PRESETS if p.key == "teams-unanswered")
        assert teams.catalog_key == "ms-365"


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
        spec = AgentSpec(
            name="Monitor",
            mcp_servers=[PersonalMcpServerRef(account="personal", catalog_key="github")],
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(WatchService, "_selected_spec", new=AsyncMock(return_value=spec)),
            patch.object(
                WatchService, "_source_conversation", new=AsyncMock(return_value=uuid.uuid4())
            ),
        ):
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


class TestPersonalConsent:
    @pytest.mark.parametrize("operation", ["create", "update", "delete"])
    @pytest.mark.parametrize(
        "ctx",
        [
            replace(_ctx(), api_key_id=uuid.uuid4(), key_internal=True),
            replace(
                _ctx(),
                api_key_id=uuid.uuid4(),
                key_scopes=frozenset({Perm.AGENTS_RUN, Perm.RUNS_VIEW}),
            ),
            replace(_ctx(), key_scopes=frozenset()),
            replace(_ctx(), subject_is_publisher_fallback=True),
            replace(_ctx(), fired_as_creator="schedule"),
            replace(_ctx(), fired_as_creator="event"),
            replace(_ctx(), routine_id=uuid.uuid4()),
            replace(
                _ctx(), source_conversation_id=uuid.uuid4(), subject_is_publisher_fallback=True
            ),
            replace(_ctx(), source_conversation_id=uuid.uuid4(), fired_as_creator="schedule"),
            replace(_ctx(), source_conversation_id=uuid.uuid4(), routine_id=uuid.uuid4()),
        ],
        ids=[
            "run-credential",
            "ordinary-key",
            "key-scopes",
            "publisher",
            "schedule",
            "event",
            "routine",
            "publisher-hint",
            "schedule-hint",
            "routine-hint",
        ],
    )
    async def test_a_script_or_background_turn_cannot_grant_private_account_reads(
        self, operation: str, ctx: AuthContext
    ) -> None:
        with patch(f"{SERVICE}.organization_repo.get_by_id", new=AsyncMock()) as lookup:
            service = WatchService(MagicMock())
            with pytest.raises(AuthorizationError, match="own consent"):
                if operation == "create":
                    await service.create(ctx, _create())
                elif operation == "update":
                    await service.update(ctx, uuid.uuid4(), WatchUpdate(is_active=True))
                else:
                    await service.delete(ctx, uuid.uuid4())
        lookup.assert_not_awaited()

    @pytest.mark.parametrize("through", ["session", "private-chat", "own-key"])
    def test_the_person_can_consent_in_a_session_their_private_chat_or_their_key(
        self, through: str
    ) -> None:
        ctx = {
            "session": _ctx(),
            "private-chat": replace(
                _ctx(),
                api_key_id=uuid.uuid4(),
                key_scopes=frozenset(),
                key_internal=True,
                source_conversation_id=uuid.uuid4(),
            ),
            "own-key": replace(
                _ctx(), api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.PERSONAL_CONSENT})
            ),
        }[through]
        WatchService._require_personal_consent(ctx)

    async def test_impersonation_cannot_set_up_or_rearm_a_watch(self) -> None:
        with (
            patch(f"{SERVICE}.current_impersonator", return_value=uuid.uuid4()),
            patch(f"{SERVICE}.organization_repo.get_by_id", new=AsyncMock()) as lookup,
        ):
            service = WatchService(MagicMock())
            with pytest.raises(AuthorizationError, match="own consent"):
                await service.create(_ctx(), _create())
            with pytest.raises(AuthorizationError, match="own consent"):
                await service.update(
                    _ctx(), uuid.uuid4(), WatchUpdate(instructions="Read more mail")
                )
        lookup.assert_not_awaited()


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
        assert changes["consecutive_failures"] == 0
        assert changes["auto_stopped_at"] is None
        assert datetime.now(UTC) - changes["health_reset_at"] < timedelta(minutes=1)
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
            patch(f"{SERVICE}.OutcomeService.resolve_watch_findings", new=AsyncMock()) as resolve,
            patch(f"{SERVICE}.OutcomeService.resolve_routine_attention", new=AsyncMock()),
        ):
            with pytest.raises(NotFoundError):
                await WatchService(MagicMock()).delete(_ctx(), uuid.uuid4())
            await WatchService(MagicMock()).delete(_ctx(), watch.id)

        delete.assert_awaited_once()
        resolve.assert_awaited_once_with(organization_id=ORG, user_id=USER, watch_id=watch.id)
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
    @staticmethod
    def _patches(
        watch,
        *,
        reading=None,
        source_reads=1,
        organization=None,
        connection=None,
        member=True,
        user=True,
        error=None,
        status=RunStatus.COMPLETED,
        check=None,
        retain_check=True,
    ):
        async def execute(ctx, agent_id, prompt, **kwargs):
            if error is not None:
                raise error
            receipt = kwargs["watch_receipt"]
            assert isinstance(receipt, WatchReadReceipt)
            receipt.completed_calls = source_reads
            receipt.check = (check or AsyncMock()) if retain_check else None
            output = kwargs["structured"]
            assert isinstance(output, list)
            output.append((reading or WatchReading()).model_dump(mode="json"))
            return "", AgentRun(
                id=uuid.uuid4(),
                status=status.value,
                agent_id=AGENT,
                agent_version_id=uuid.uuid4(),
                model_label="chosen-model",
                routine_kind="watch",
                routine_origin_id=watch.id,
            )

        run = AsyncMock(side_effect=execute)
        return (
            patch(f"{LOOK}.watch_repo.get_by_id", new=AsyncMock(return_value=watch)),
            patch(f"{LOOK}.watch_repo.mark_attempt", new=AsyncMock()),
            patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock(return_value=True)),
            patch(f"{LOOK}.watch_repo.claim_report_activation", new=AsyncMock(return_value=True)),
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
                f"{LOOK}.user_repo.get_by_id",
                new=AsyncMock(
                    return_value=MagicMock(
                        id=USER, is_active=True, locale="pl", time_zone="Europe/Warsaw"
                    )
                    if user
                    else None
                ),
            ),
            patch(
                f"{LOOK}.agent_run_repo.proactive_spend_since",
                new=AsyncMock(return_value=Decimal(0)),
            ),
            patch(f"{LOOK}.suggestion_repo.titles_for_watch", new=AsyncMock(return_value=["Old"])),
            patch(f"{LOOK}.suggestion_repo.propose", new=AsyncMock(return_value=None)),
            patch(f"{LOOK}.OutcomeService.track_finding", new=AsyncMock()),
            patch(f"{LOOK}.OutcomeService.resolve_routine_budget", new=AsyncMock()),
            patch(f"{LOOK}.OutcomeService.resolve_routine_failure", new=AsyncMock()),
            patch(f"{LOOK}.OutcomeService.resolve_routine_attention", new=AsyncMock()),
            patch(f"{LOOK}.NotificationService.watch_blocked", new=AsyncMock()),
            patch(f"{LOOK}.NotificationService.routine_budget_paused", new=AsyncMock()),
            patch(
                f"{LOOK}.conversation_repo.get_conversation_by_id",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(f"{LOOK}.AgentRunnerService", return_value=MagicMock(execute=run)),
        ), run

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
    def test_links_only_open_web_addresses(self, url, kept):
        assert (_web_link(url) is not None) is kept

    def test_same_item_and_watch_keep_their_key(self):
        one, other = uuid.uuid4(), uuid.uuid4()
        assert _key(one, "PR 12") == _key(one, " PR 12 ")
        assert _key(one, "PR 12") != _key(other, "PR 12")
        assert len(_key(one, "PR 12")) <= 64

    @pytest.mark.security
    async def test_selected_agent_executes_with_version_and_person_budget(self):
        watch = _watch(pinned_version_id=uuid.uuid4(), exclusions=["dependabot"])
        patches, execute = self._patches(watch)
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            mark_ran = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock()))
            assert await WatchLook(MagicMock()).look(watch.id) == 0
        ctx, agent_id, prompt = execute.await_args.args
        assert agent_id == AGENT and ctx.user_id == USER and ctx.routine_id == watch.id
        assert ctx.routine_kind == "watch" and ctx.fired_as_creator == "schedule"
        assert execute.await_args.kwargs["version_id"] == watch.pinned_version_id
        assert execute.await_args.kwargs["run_limit_usd"] == Decimal("1")
        assert '"not_wanted": ["dependabot"]' in prompt
        assert '"already_reported": ["Old"]' in prompt
        mark_ran.assert_awaited_once()

    async def test_new_findings_are_recorded_once_and_only_requested_urgency_notifies(self):
        watch = _watch(urgent=True)
        reading = WatchReading(
            findings=[
                Found(key="1", title="Review #1", url="https://github.com/o/r/pull/1", urgent=True),
                Found(key="2", title="Review #2", url="javascript:void(0)"),
                Found(key="3", title="Seen before", urgent=True),
            ]
        )
        patches, _ = self._patches(watch, reading=reading)
        propose = AsyncMock(
            side_effect=[MagicMock(id=uuid.uuid4(), title="Review #1"), MagicMock(), None]
        )
        finding = AsyncMock()
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            stack.enter_context(patch(f"{LOOK}.suggestion_repo.propose", new=propose))
            stack.enter_context(
                patch(
                    f"{LOOK}.NotificationService",
                    return_value=MagicMock(finding=finding, watch_blocked=AsyncMock()),
                )
            )
            assert await WatchLook(MagicMock()).look(watch.id) == 2
        first, second, _ = (call.kwargs for call in propose.await_args_list)
        assert first["urgent"] is True and second["urgent"] is False
        assert first["payload"]["url"].startswith("https://") and second["payload"]["url"] is None
        finding.assert_awaited_once()

    async def test_a_nonurgent_watch_keeps_urgent_findings_in_the_inbox(self):
        patches, _ = self._patches(
            _watch(urgent=False),
            reading=WatchReading(findings=[Found(key="1", title="Invoice", urgent=True)]),
        )
        finding = AsyncMock()
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            stack.enter_context(
                patch(
                    f"{LOOK}.suggestion_repo.propose",
                    new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
                )
            )
            stack.enter_context(
                patch(
                    f"{LOOK}.NotificationService",
                    return_value=MagicMock(finding=finding, watch_blocked=AsyncMock()),
                )
            )
            assert await WatchLook(MagicMock()).look(uuid.uuid4()) == 1
        finding.assert_not_awaited()

    @pytest.mark.parametrize(
        ("status", "source_reads", "expected"),
        [
            (RunStatus.COMPLETED, 0, WatchAttemptStatus.NOT_COMPLETED),
            (RunStatus.FAILED, 1, WatchAttemptStatus.NOT_COMPLETED),
            (RunStatus.BUDGET_EXCEEDED, 0, WatchAttemptStatus.BUDGET_PAUSED),
        ],
    )
    async def test_incomplete_checks_are_not_successful_empty_readings(
        self, status, source_reads, expected
    ):
        patches, _ = self._patches(_watch(), status=status, source_reads=source_reads)
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            attempt = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_attempt", new=AsyncMock()))
            success = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock()))
            assert await WatchLook(MagicMock()).look(uuid.uuid4()) == 0
        assert attempt.await_args.kwargs["status"] == expected
        success.assert_not_awaited()

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (BadRequestError(message="Unavailable source"), WatchAttemptStatus.SOURCE_UNAVAILABLE),
            (AuthorizationError(message="Revoked"), WatchAttemptStatus.ACCESS_REVOKED),
            (NotFoundError(message="Agent gone"), WatchAttemptStatus.ACCESS_REVOKED),
            (RunFailedError(), WatchAttemptStatus.NOT_COMPLETED),
        ],
    )
    async def test_source_and_model_failures_are_explicit(self, error, expected):
        patches, _ = self._patches(_watch(), error=error)
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            attempt = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_attempt", new=AsyncMock()))
            assert await WatchLook(MagicMock()).look(uuid.uuid4()) == 0
        assert attempt.await_args.kwargs["status"] == expected

    @pytest.mark.parametrize(
        "case", ["gone", "paused", "legacy", "off", "left", "inactive-user", "changed-owner"]
    )
    async def test_no_model_is_called_without_a_live_approved_actor_and_agent(self, case):
        watch = (
            None
            if case == "gone"
            else _watch(is_active=case != "paused", agent_id=None if case == "legacy" else AGENT)
        )
        patches, execute = self._patches(
            watch,
            organization=_organization(on=case != "off"),
            member=case != "left",
            user=case != "inactive-user",
            connection=_connection(owner=uuid.uuid4()) if case == "changed-owner" else None,
        )
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            assert await WatchLook(MagicMock()).look(uuid.uuid4()) == 0
        execute.assert_not_awaited()

    @pytest.mark.security
    async def test_person_budget_exhaustion_precedes_the_model_call(self):
        patches, execute = self._patches(_watch())
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            stack.enter_context(
                patch(
                    f"{LOOK}.agent_run_repo.proactive_spend_since",
                    new=AsyncMock(return_value=Decimal("1")),
                )
            )
            notice = stack.enter_context(
                patch(f"{LOOK}.NotificationService.routine_budget_paused", new=AsyncMock())
            )
            attempt = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_attempt", new=AsyncMock()))
            assert await WatchLook(MagicMock()).look(uuid.uuid4()) == 0
        assert attempt.await_args.kwargs["status"] == WatchAttemptStatus.BUDGET_PAUSED
        execute.assert_not_awaited()
        notice.assert_awaited_once()
        assert notice.await_args.kwargs["routine_kind"] == "watch"
        assert notice.await_args.kwargs["spent"] == Decimal("1")

    async def test_revocation_after_reading_prevents_recording_findings(self):
        patches, _ = self._patches(
            _watch(),
            reading=WatchReading(findings=[Found(key="1", title="Private")]),
            check=AsyncMock(side_effect=AuthorizationError(message="Stopped")),
        )
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            propose = stack.enter_context(patch(f"{LOOK}.suggestion_repo.propose", new=AsyncMock()))
            assert await WatchLook(MagicMock()).look(uuid.uuid4()) == 0
        propose.assert_not_awaited()

    async def test_a_failed_result_write_does_not_become_a_successful_check(self):
        patches, _ = self._patches(_watch())
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            stack.enter_context(
                patch.object(
                    WatchLook, "_record", new=AsyncMock(side_effect=RuntimeError("write failed"))
                )
            )
            mark_ran = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock()))
            with pytest.raises(RuntimeError, match="write failed"):
                await WatchLook(MagicMock()).look(uuid.uuid4())
        mark_ran.assert_not_awaited()


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
            patch.object(WatchLook, "expire_due", new=AsyncMock(return_value=0)) as expire,
            patch.object(WatchLook, "due", new=AsyncMock(return_value=[watch])),
            patch.object(WatchLook, "look", new=AsyncMock(return_value=3)),
            patch(f"{FACADE}.enqueue", new=enqueue),
        ):
            service = ProactiveService(MagicMock())
            assert await service.sweep_watches(now=NOW) == 1
            assert await service.look_through(watch.id) == 3

        expire.assert_awaited_once_with(now=NOW)
        (_, task, payload) = enqueue.await_args.args
        assert task is LOOK_THROUGH_WATCH and payload.watch_id == watch.id
        assert enqueue.await_args.kwargs["organization_id"] == ORG
        assert enqueue.await_args.kwargs["dedupe_key"] == f"watch:{watch.id}"
        assert enqueue.await_args.kwargs["concurrency_key"] == f"proactivity:{ORG}:{watch.user_id}"

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

    @pytest.mark.parametrize(
        "method,path",
        [("get", "/me/watches"), ("delete", f"/me/watches/{uuid.uuid4()}")],
        ids=["list", "delete"],
    )
    async def test_unrelated_api_key_scope_cannot_read_or_delete(
        self, client: AsyncClient, service, method: str, path: str
    ):
        app.dependency_overrides[get_auth_context] = lambda: replace(
            _ctx(), api_key_id=uuid.uuid4(), key_scopes=frozenset()
        )
        response = await getattr(client, method)(f"/api/v1{path}")
        assert response.status_code == 403
        service.list_mine.assert_not_called()
        service.delete.assert_not_called()

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
                "agent_id": str(AGENT),
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
                "agent_id": str(AGENT),
                "connection_id": str(uuid.uuid4()),
                "title": "Too often",
                "instructions": "Everything.",
                "interval_minutes": 5,
            },
        )
        assert response.status_code == 422


@pytest.mark.parametrize("allowed", ["allowed", "refused", "wrong-owner", "deleted"])
async def test_new_findings_return_to_the_current_authorized_source_conversation(allowed: str):
    conversation_id = uuid.uuid4()
    watch = _watch(source_conversation_id=conversation_id)
    reading = WatchReading(findings=[Found(key="1", title="Needs review", detail="Waiting on you")])
    patches, _ = TestOneLook._patches(watch, reading=reading)
    delivery = AsyncMock()
    lookup = AsyncMock(
        return_value=MagicMock(id=conversation_id, user_id=USER, organization_id=ORG)
    )
    if allowed == "wrong-owner":
        lookup.return_value.user_id = uuid.uuid4()
    if allowed == "refused":
        lookup.side_effect = AuthorizationError(message="Project access was revoked")
    attempt = AsyncMock()
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        stack.enter_context(
            patch(
                f"{LOOK}.suggestion_repo.propose",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            )
        )
        stack.enter_context(
            patch(f"{LOOK}.ConversationService", return_value=MagicMock(get_conversation=lookup))
        )
        if allowed == "deleted":
            stack.enter_context(
                patch(
                    f"{LOOK}.conversation_repo.get_conversation_by_id",
                    new=AsyncMock(return_value=None),
                )
            )
        stack.enter_context(patch(f"{LOOK}.conversation_repo.create_message", new=delivery))
        stack.enter_context(patch(f"{LOOK}.watch_repo.mark_attempt", new=attempt))
        assert await WatchLook(MagicMock()).look(watch.id) == 1
    if allowed == "allowed":
        assert delivery.await_args.kwargs["conversation_id"] == conversation_id
        assert delivery.await_args.kwargs["agent_id"] == AGENT
        assert "Needs review" in delivery.await_args.kwargs["content"]
        attempt.assert_not_awaited()
    else:
        delivery.assert_not_awaited()
        assert attempt.await_args.kwargs["status"] == WatchAttemptStatus.DELIVERY_UNAVAILABLE


async def test_legacy_watches_and_expired_watches_do_not_queue_model_work():
    legacy = _watch(agent_id=None, approved_sources=None)
    expired = _watch(ends_at=NOW - timedelta(seconds=1))
    update, schedule = AsyncMock(), AsyncMock()
    with (
        patch(f"{LOOK}.watch_repo.claim_due", new=AsyncMock(return_value=[legacy, expired])),
        patch(f"{LOOK}.organization_repo.get_by_id", new=AsyncMock(return_value=_organization())),
        patch(f"{LOOK}.watch_repo.schedule", new=schedule),
        patch(f"{LOOK}.watch_repo.update_fields", new=update),
    ):
        assert await WatchLook(MagicMock()).due(now=NOW) == []
    schedule.assert_awaited_once()
    assert schedule.await_args.kwargs["watch_id"] == legacy.id
    assert update.await_args.kwargs["changes"] == {"is_active": False}


@pytest.mark.parametrize("pin", [False, True])
async def test_watch_selection_resolves_a_runnable_publication_or_immutable_pin(pin: bool):
    spec = AgentSpec(name="Monitor")
    registry = MagicMock(
        get_runnable_spec=AsyncMock(return_value=(MagicMock(), spec, uuid.uuid4())),
        get_pinned_spec=AsyncMock(return_value=(MagicMock(), spec, uuid.uuid4())),
        with_assistant_guidance=AsyncMock(return_value=spec),
    )
    version = uuid.uuid4() if pin else None
    environment = None if pin else uuid.uuid4()
    with patch(f"{SERVICE}.AgentRegistryService", return_value=registry):
        service = WatchService(MagicMock())
        assert (
            await service._selected_spec(
                _ctx(), AGENT, environment_id=environment, pinned_version_id=version
            )
            == spec
        )
        with pytest.raises(BadRequestError):
            await service._selected_spec(
                _ctx(), AGENT, environment_id=uuid.uuid4(), pinned_version_id=uuid.uuid4()
            )
    if pin:
        registry.get_pinned_spec.assert_awaited_once_with(_ctx(), AGENT, version)
    else:
        registry.get_runnable_spec.assert_awaited_once_with(
            _ctx(), AGENT, environment_id=environment
        )


@pytest.mark.parametrize(
    "destination", ["primary", "private", "wrong-owner", "wrong-org", "missing"]
)
async def test_watch_delivery_admission_keeps_the_persons_own_source(destination: str):
    target = uuid.uuid4()
    ctx = _ctx() if destination == "primary" else replace(_ctx(), source_conversation_id=target)
    conversation = (
        None
        if destination == "missing"
        else MagicMock(
            id=target,
            user_id=uuid.uuid4() if destination == "wrong-owner" else USER,
            organization_id=uuid.uuid4() if destination == "wrong-org" else ORG,
        )
    )
    with (
        patch(
            f"{SERVICE}.ConversationService",
            return_value=MagicMock(get_conversation=AsyncMock(return_value=conversation)),
        ),
        patch(
            f"{SERVICE}.PrimaryConversationService",
            return_value=MagicMock(ensure=AsyncMock(return_value=target)),
        ) as primary,
    ):
        service = WatchService(MagicMock())
        if destination in {"wrong-owner", "wrong-org", "missing"}:
            with pytest.raises(NotFoundError):
                await service._source_conversation(ctx, AGENT)
        else:
            assert await service._source_conversation(ctx, AGENT) == target
        if destination == "primary":
            primary.return_value.ensure.assert_awaited_once_with(
                organization_id=ORG, user_id=USER, agent_id=AGENT
            )


@pytest.mark.parametrize("mode", ["legacy", "agent", "review", "version"])
async def test_watch_edits_refresh_sources_only_when_the_person_explicitly_approves_them(mode: str):
    original_context = uuid.uuid4()
    watch = _watch(agent_id=None if mode == "legacy" else AGENT)
    connection = _named(_connection())
    original = AgentSpec(
        name="Monitor",
        context_ids=[original_context],
        mcp_servers=[PersonalMcpServerRef(account="personal", catalog_key="github")],
    )
    watch.approved_sources = approve_sources(original, connection).model_dump(mode="json")
    next_spec = original.model_copy(update={"context_ids": [original_context, uuid.uuid4()]})
    update, patches = TestChangingOne._patches(watch, _organization(), connection)
    data = WatchUpdate(
        **(
            {"agent_id": AGENT}
            if mode == "legacy"
            else {"agent_id": uuid.uuid4()}
            if mode == "agent"
            else {"review_sources": True}
            if mode == "review"
            else {"pinned_version_id": uuid.uuid4()}
        )
    )
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        stack.enter_context(
            patch.object(WatchService, "_selected_spec", new=AsyncMock(return_value=next_spec))
        )
        stack.enter_context(
            patch.object(
                WatchService, "_source_conversation", new=AsyncMock(return_value=uuid.uuid4())
            )
        )
        await WatchService(MagicMock()).update(_ctx(), watch.id, data)
    changes = update.await_args.kwargs["changes"]
    if mode == "version":
        assert "approved_sources" not in changes
    else:
        assert changes["approved_sources"]["context_ids"] == [
            str(value) for value in next_spec.context_ids
        ]
    if mode == "agent":
        assert changes["environment_id"] is None and changes["pinned_version_id"] is None
    if mode == "legacy":
        assert changes["source_conversation_id"] is not None and changes["next_run_at"] is not None


async def test_a_legacy_watch_cannot_resume_without_choosing_its_agent():
    watch = _watch(agent_id=None, is_active=False)
    _, patches = TestChangingOne._patches(watch, _organization(), _named(_connection()))
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        pytest.raises(BadRequestError, match="Select the agent"),
    ):
        await WatchService(MagicMock()).update(_ctx(), watch.id, WatchUpdate(is_active=True))
    with pytest.raises(BadRequestError, match="future"):
        WatchService._end(NOW)


async def test_an_expired_watch_stops_before_executing_its_selected_agent():
    watch = _watch(ends_at=datetime.now(UTC) - timedelta(seconds=1))
    patches, execute = TestOneLook._patches(watch)
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        update = stack.enter_context(patch(f"{LOOK}.watch_repo.update_fields", new=AsyncMock()))
        assert await WatchLook(MagicMock()).look(watch.id) == 0
    execute.assert_not_awaited()
    assert update.await_args.kwargs["changes"] == {"is_active": False}


async def test_revocation_between_source_read_and_first_result_blocks_result_delivery():
    watch = _watch()
    check = AsyncMock(side_effect=[None, AuthorizationError(message="Paused")])
    patches, _ = TestOneLook._patches(
        watch, reading=WatchReading(findings=[Found(key="1", title="Review")]), check=check
    )
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        propose = stack.enter_context(patch(f"{LOOK}.suggestion_repo.propose", new=AsyncMock()))
        attempt = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_attempt", new=AsyncMock()))
        success = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock()))
        assert await WatchLook(MagicMock()).look(watch.id) == 0
    propose.assert_not_awaited()
    success.assert_not_awaited()
    assert attempt.await_args.kwargs["status"] == WatchAttemptStatus.ACCESS_REVOKED


async def test_a_watch_without_its_live_authority_check_fails_loudly():
    watch = _watch()
    patches, _ = TestOneLook._patches(watch, retain_check=False)
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        with pytest.raises(RuntimeError, match="authorization check"):
            await WatchLook(MagicMock()).look(watch.id)


async def test_a_watch_cannot_be_edited_to_end_in_the_past():
    watch = _watch()
    _, patches = TestChangingOne._patches(watch, _organization(), _named(_connection()))
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        pytest.raises(BadRequestError, match="future"),
    ):
        await WatchService(MagicMock()).update(_ctx(), watch.id, WatchUpdate(ends_at=NOW))


@pytest.mark.parametrize("mode", ["changes", "every_check"])
@pytest.mark.parametrize("source_reads", [0, 1])
async def test_a_requested_no_change_report_is_delivered_only_after_a_successful_read(
    mode, source_reads
):
    watch = _watch(report_mode=mode, source_conversation_id=uuid.uuid4())
    patches, _ = TestOneLook._patches(watch, source_reads=source_reads)
    message, report = AsyncMock(), AsyncMock()
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        stack.enter_context(
            patch(
                f"{LOOK}.ConversationService",
                return_value=MagicMock(
                    get_conversation=AsyncMock(
                        return_value=MagicMock(
                            id=watch.source_conversation_id, organization_id=ORG, user_id=USER
                        )
                    )
                ),
            )
        )
        stack.enter_context(patch(f"{LOOK}.conversation_repo.create_message", new=message))
        stack.enter_context(
            patch(f"{LOOK}.agent_repo.get", new=AsyncMock(return_value=MagicMock(id=AGENT)))
        )
        stack.enter_context(
            patch(
                f"{LOOK}.NotificationService",
                return_value=MagicMock(routine_finished=report, watch_blocked=AsyncMock()),
            )
        )
        assert await WatchLook(MagicMock()).look(watch.id) == 0
    if mode == "every_check" and source_reads:
        assert "Brak nowych istotnych zmian" in message.await_args.kwargs["content"]
        assert report.await_args.kwargs["source_conversation_id"] == watch.source_conversation_id
        assert report.await_args.kwargs["creator_id"] == USER
    else:
        message.assert_not_awaited()
        report.assert_not_awaited()


async def test_a_retried_report_activation_does_not_pay_for_a_second_read():
    watch = _watch(report_mode="every_check", last_reported_activation=NOW)
    patches, execute = TestOneLook._patches(watch)
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        assert await WatchLook(MagicMock()).look(watch.id, scheduled_for=NOW) == 0
    execute.assert_not_awaited()


async def test_only_the_report_writer_that_claimed_the_activation_delivers():
    watch = _watch(report_mode="every_check")
    patches, _ = TestOneLook._patches(watch)
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        stack.enter_context(
            patch(f"{LOOK}.watch_repo.claim_report_activation", new=AsyncMock(return_value=False))
        )
        notifications = stack.enter_context(patch(f"{LOOK}.NotificationService"))
        assert await WatchLook(MagicMock()).look(watch.id, scheduled_for=NOW) == 0
    notifications.assert_not_called()


async def test_lost_agent_access_rolls_back_a_requested_report_instead_of_claiming_delivery():
    watch = _watch(report_mode="every_check")
    patches, _ = TestOneLook._patches(watch)
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        stack.enter_context(patch(f"{LOOK}.agent_repo.get", new=AsyncMock(return_value=None)))
        attempt = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_attempt", new=AsyncMock()))
        success = stack.enter_context(patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock()))
        assert await WatchLook(MagicMock()).look(watch.id) == 0
    success.assert_not_awaited()
    assert attempt.await_args.kwargs["status"] == WatchAttemptStatus.ACCESS_REVOKED


async def test_an_unavailable_draft_chat_is_a_delivery_problem_not_a_failed_source_check():
    from app.core.exceptions import ConflictError

    watch = _watch()
    patches, _ = TestOneLook._patches(watch)
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        stack.enter_context(
            patch.object(
                WatchLook,
                "_record",
                new=AsyncMock(side_effect=ConflictError(message="Working chat unavailable")),
            )
        )
        attempted = stack.enter_context(patch.object(WatchLook, "_mark_attempt", new=AsyncMock()))
        assert await WatchLook(MagicMock()).look(watch.id) == 0
    assert attempted.await_args.kwargs["status"] == WatchAttemptStatus.DELIVERY_UNAVAILABLE


@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize("current", [False, True])
async def test_watch_drafts_have_one_owned_working_chat_and_stale_attempts_do_not_resolve_new_incidents(
    published, current
):
    watch = _watch(urgent=True)
    patches, _ = TestOneLook._patches(
        watch,
        reading=WatchReading(
            findings=[
                Found(
                    key="mail-1",
                    title="Draft reply",
                    content="A proposed reply",
                    revision="v2",
                    urgent=True,
                )
            ]
        ),
    )
    draft = uuid.uuid4() if published else None
    publish = AsyncMock(return_value=draft)
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        stack.enter_context(patch(f"{LOOK}.RoutineFindingService.publish", new=publish))
        stack.enter_context(
            patch(f"{LOOK}.watch_repo.mark_ran", new=AsyncMock(return_value=current))
        )
        assert await WatchLook(MagicMock()).look(watch.id) == int(published)
    assert publish.await_args.kwargs["origin_kind"] == "watch"
    assert publish.await_args.kwargs["item"].content == "A proposed reply"
    assert publish.await_args.kwargs["notify"] is True
