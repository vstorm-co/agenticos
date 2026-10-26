"""The platform's own initiative, all of it in background jobs (#2301).

What is asserted is what a person would notice: nothing is spent past a limit or
without a starter agent, a model call leaves a run row either way, the nightly
look proposes only what is new and offers nothing twice, the sweep reaches each
person early in their own morning, a role pack makes each routine once, and a
welcome that fails on one platform still greets on the next.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.suggestion import SuggestionKind
from app.repositories.member import SweepCandidate
from app.schemas.user import WorkingHours
from app.services.proactive import _role_pack, _thinker, _welcome
from app.services.proactive._nightly import (
    NightlyLook,
    NightlyReading,
    ProfileUpdate,
    RepeatedRequest,
)
from app.services.proactive._thinker import ProactiveThinker
from app.services.proactive.facade import _STARTER_SLUG, ProactiveService, _its_time
from app.services.role_packs import PACKS, pack, routines_of
from app.worker.jobs import BRIEF_PERSON, INSTALL_ROLE_PACK, THINK_FOR_PERSON, WELCOME_MEMBER

pytestmark = pytest.mark.anyio

THINKER = "app.services.proactive._thinker"
NIGHTLY = "app.services.proactive._nightly"
FACADE = "app.services.proactive.facade"
WELCOME = "app.services.proactive._welcome"
PACK = "app.services.proactive._role_pack"

ORG = uuid.uuid4()
USER = uuid.uuid4()
MODEL = uuid.uuid4()


def _ctx() -> AuthContext:
    return AuthContext(user_id=USER, organization_id=ORG, role=OrgRoleName.MEMBER)


def _agent(*, published: bool = True) -> MagicMock:
    return MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4() if published else None)


def _organization(
    limit: str = "1",
    cap: str | None = None,
    *,
    enabled: bool = True,
    watches: bool = False,
    model: uuid.UUID | None = MODEL,
) -> MagicMock:
    return MagicMock(
        proactive_enabled=enabled,
        proactive_watches_enabled=watches,
        proactive_model_profile_id=model,
        proactive_limit_usd=Decimal(limit),
        monthly_budget_usd=None if cap is None else Decimal(cap),
    )


def test_the_facade_and_the_thinker_name_the_same_starter_agent():
    assert _STARTER_SLUG == _thinker.STARTER_SLUG


class TestTheLimits:
    async def test_an_organization_without_a_published_starter_agent_gets_nothing(self):
        thinker = ProactiveThinker(MagicMock())
        with patch(f"{THINKER}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)):
            assert await thinker.starter_agent(ORG) is None
        with patch(
            f"{THINKER}.agent_repo.get_by_slug",
            new=AsyncMock(return_value=_agent(published=False)),
        ):
            assert await thinker.starter_agent(ORG) is None

    @pytest.mark.parametrize(
        ("organization", "org_spent", "mine", "allowed"),
        [
            (None, "0", "0", False),
            (_organization(enabled=False), "0", "0", False),
            (_organization(model=None), "0", "0", False),
            (_organization(limit="0"), "0", "0", False),
            (_organization(cap="10"), "10", "0", False),
            (_organization(), "0", "1", False),
            (_organization(cap="10"), "9", "0.99", True),
        ],
        ids=[
            "no-organization",
            "turned-off",
            "no-model-chosen",
            "zero-limit",
            "org-cap-reached",
            "person-limit-reached",
            "room",
        ],
    )
    async def test_background_work_spends_only_where_turned_on_and_inside_both_limits(
        self, organization, org_spent, mine, allowed
    ):
        with (
            patch(
                f"{THINKER}.organization_repo.get_by_id", new=AsyncMock(return_value=organization)
            ),
            patch(
                f"{THINKER}.organization_monthly_spend",
                new=AsyncMock(return_value=Decimal(org_spent)),
            ),
            patch(
                f"{THINKER}.agent_run_repo.proactive_spend_since",
                new=AsyncMock(return_value=Decimal(mine)),
            ),
        ):
            # Room is the organization's chosen model; anything else is nothing.
            assert await ProactiveThinker(MagicMock()).allowance(_ctx(), "nightly") == (
                MODEL if allowed else None
            )

    @pytest.mark.parametrize(
        ("organization", "feature", "allowed"),
        [
            (_organization(enabled=True, watches=False), "watches", False),
            (_organization(enabled=False, watches=True), "watches", True),
            (_organization(enabled=False, watches=True), "nightly", False),
        ],
        ids=["watches-off", "watches-on-nightly-off", "nightly-off"],
    )
    async def test_each_feature_answers_to_its_own_switch(self, organization, feature, allowed):
        """The watches and the nightly look share a model and a limit, not a switch."""
        with (
            patch(
                f"{THINKER}.organization_repo.get_by_id", new=AsyncMock(return_value=organization)
            ),
            patch(
                f"{THINKER}.agent_run_repo.proactive_spend_since",
                new=AsyncMock(return_value=Decimal(0)),
            ),
        ):
            assert await ProactiveThinker(MagicMock()).allowance(_ctx(), feature) == (
                MODEL if allowed else None
            )

    async def test_nobody_signed_in_has_no_limit_to_spend_against(self):
        ctx = AuthContext(user_id=None, organization_id=ORG, role=OrgRoleName.MEMBER)
        with patch(
            f"{THINKER}.organization_repo.get_by_id", new=AsyncMock(return_value=_organization())
        ):
            assert await ProactiveThinker(MagicMock()).allowance(ctx, "nightly") is None


def _session() -> MagicMock:
    """A session the thinker can commit its run on."""
    return MagicMock(commit=AsyncMock())


class TestThinking:
    @staticmethod
    def _patches(model, *, version=True, resolve_error=None):
        request = SimpleNamespace(
            build=lambda: model,
            label="Sonnet",
            provider="anthropic",
            model="claude",
            secret_id=None,
        )
        resolve = (
            AsyncMock(side_effect=resolve_error)
            if resolve_error
            else AsyncMock(return_value=request)
        )
        run = MagicMock(id=uuid.uuid4())
        stored = MagicMock(id=uuid.uuid4())
        stored.spec = {"name": "AgenticOS"}
        return (
            patch(f"{THINKER}.agent_repo.get_by_slug", new=AsyncMock(return_value=_agent())),
            patch.object(ProactiveThinker, "allowance", new=AsyncMock(return_value=MODEL)),
            patch(
                f"{THINKER}.agent_repo.get_version",
                new=AsyncMock(return_value=stored if version else None),
            ),
            patch(f"{THINKER}.ModelProfileService", return_value=MagicMock(resolve=resolve)),
            patch(f"{THINKER}.agent_run_repo.create_run", new=AsyncMock(return_value=run)),
            patch(f"{THINKER}.agent_run_repo.finish_run", new=AsyncMock()),
        )

    async def test_an_answer_is_returned_and_the_run_is_written_down(self):
        get_slug, limits, version, profiles, create, finish = self._patches(TestModel())
        with (
            get_slug,
            limits,
            version,
            profiles as service,
            create as create_run,
            finish as finish_run,
        ):
            answer = await ProactiveThinker(_session()).think(
                _ctx(),
                feature="nightly",
                output_type=NightlyReading,
                instructions="Read.",
                prompt="{}",
            )

        assert isinstance(answer, NightlyReading)
        # On the model the organization chose for it, not the agent's own.
        assert service.return_value.resolve.await_args.kwargs == {"profile_id": MODEL}
        assert create_run.await_args.kwargs["surface"] == RunSurface.PROACTIVE.value
        assert create_run.await_args.kwargs["user_id"] == USER
        finished = finish_run.await_args.kwargs
        assert finished["status"] == RunStatus.COMPLETED.value
        # The test model is not priced: recorded as zero and marked partial, not lost.
        assert finished["cost_usd"] == Decimal(0)
        assert finished["cost_is_partial"] is True

    async def test_a_watch_reads_through_the_tools_it_is_given_before_answering(self):
        from pydantic_ai.toolsets import FunctionToolset

        read: list[str] = []

        def list_pull_requests() -> str:
            """The pull requests waiting on a review."""
            read.append("listed")
            return "#12 waiting since Monday"

        get_slug, limits, version, profiles, create, finish = self._patches(TestModel())
        with get_slug, limits, version, profiles, create, finish:
            answer = await ProactiveThinker(_session()).think(
                _ctx(),
                feature="watches",
                output_type=NightlyReading,
                instructions="Read.",
                prompt="{}",
                toolsets=[FunctionToolset([list_pull_requests])],
            )

        assert isinstance(answer, NightlyReading)
        assert read == ["listed"]

    async def test_a_model_that_fails_leaves_a_failed_run_and_no_answer(self):
        def broken(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            raise ModelHTTPError(status_code=500, model_name="claude")

        get_slug, limits, version, profiles, create, finish = self._patches(FunctionModel(broken))
        with get_slug, limits, version, profiles, create, finish as finish_run:
            answer = await ProactiveThinker(_session()).think(
                _ctx(),
                feature="nightly",
                output_type=NightlyReading,
                instructions="Read.",
                prompt="{}",
            )

        assert answer is None
        assert finish_run.await_args.kwargs["status"] == RunStatus.FAILED.value
        assert finish_run.await_args.kwargs["error"]

    async def test_the_run_is_committed_before_the_model_is_called(self):
        """A worker killed mid-call must leave the run behind for the limit to count."""
        session = _session()
        committed_at_call: list[bool] = []

        def answer(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            committed_at_call.append(session.commit.await_count == 1)
            raise ModelHTTPError(status_code=500, model_name="claude")

        get_slug, limits, version, profiles, create, finish = self._patches(FunctionModel(answer))
        with get_slug, limits, version, profiles, create, finish:
            await ProactiveThinker(session).think(
                _ctx(),
                feature="nightly",
                output_type=NightlyReading,
                instructions="Read.",
                prompt="{}",
            )

        assert committed_at_call == [True]

    async def test_a_run_that_fails_after_the_model_answered_books_what_it_used(self):
        """Output validation out of retries raises after the provider charged."""

        def unreadable(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("not the reading")])

        get_slug, limits, version, profiles, create, finish = self._patches(
            FunctionModel(unreadable)
        )
        with get_slug, limits, version, profiles, create, finish as finish_run:
            answer = await ProactiveThinker(_session()).think(
                _ctx(),
                feature="nightly",
                output_type=NightlyReading,
                instructions="Read.",
                prompt="{}",
            )

        assert answer is None
        finished = finish_run.await_args.kwargs
        assert finished["status"] == RunStatus.FAILED.value
        assert finished["input_tokens"] > 0
        assert finished["output_tokens"] > 0

    async def test_a_model_nobody_may_use_spends_nothing(self):
        get_slug, limits, version, profiles, create, finish = self._patches(
            TestModel(), resolve_error=BadRequestError(message="no model")
        )
        with get_slug, limits, version, profiles, create as create_run, finish:
            assert (
                await ProactiveThinker(_session()).think(
                    _ctx(),
                    feature="nightly",
                    output_type=NightlyReading,
                    instructions="",
                    prompt="",
                )
                is None
            )
        create_run.assert_not_awaited()

    async def test_nothing_is_called_without_a_version_a_starter_or_room_in_the_limit(self):
        get_slug, limits, version, profiles, create, finish = self._patches(
            TestModel(), version=False
        )
        with get_slug, limits, version, profiles, create as create_run, finish:
            assert (
                await ProactiveThinker(_session()).think(
                    _ctx(),
                    feature="nightly",
                    output_type=NightlyReading,
                    instructions="",
                    prompt="",
                )
                is None
            )
        create_run.assert_not_awaited()

        with patch(f"{THINKER}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)):
            assert (
                await ProactiveThinker(_session()).think(
                    _ctx(),
                    feature="nightly",
                    output_type=NightlyReading,
                    instructions="",
                    prompt="",
                )
                is None
            )

        with (
            patch(f"{THINKER}.agent_repo.get_by_slug", new=AsyncMock(return_value=_agent())),
            patch.object(ProactiveThinker, "allowance", new=AsyncMock(return_value=None)),
        ):
            assert (
                await ProactiveThinker(_session()).think(
                    _ctx(),
                    feature="nightly",
                    output_type=NightlyReading,
                    instructions="",
                    prompt="",
                )
                is None
            )


def _user(**overrides):
    values = {
        "id": USER,
        "is_active": True,
        "locale": "pl",
        "time_zone": "Europe/Warsaw",
        "job_title": None,
        "about": None,
        "working_hours": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestTheNightlyLook:
    @staticmethod
    def _patches(
        *, user=None, member=True, agent=True, last=None, requests=(), reading=None, starters=None
    ):
        thinker = MagicMock()
        thinker.starter_agent = AsyncMock(return_value=_agent() if agent else None)
        thinker.think = AsyncMock(return_value=reading)
        return {
            "thinker": thinker,
            "patches": [
                patch(
                    f"{NIGHTLY}.user_repo.get_by_id", new=AsyncMock(return_value=user or _user())
                ),
                patch(
                    f"{NIGHTLY}.member_repo.get_active",
                    new=AsyncMock(
                        return_value=(
                            MagicMock(role="member", personal_starters=starters) if member else None
                        )
                    ),
                ),
                patch(
                    f"{NIGHTLY}.agent_run_repo.last_proactive_run_at",
                    new=AsyncMock(return_value=last),
                ),
                patch(
                    f"{NIGHTLY}.conversation_repo.person_requests_since",
                    new=AsyncMock(return_value=list(requests)),
                ),
                patch(f"{NIGHTLY}.memory_repo.list_for_owner", new=AsyncMock(return_value=[])),
                patch(
                    f"{NIGHTLY}.agent_trigger_repo.prompts_created_by",
                    new=AsyncMock(return_value=[]),
                ),
                patch(
                    f"{NIGHTLY}.mcp_connection_repo.list_for_user",
                    new=AsyncMock(return_value=([], 0)),
                ),
                patch(f"{NIGHTLY}.user_repo.update", new=AsyncMock()),
                patch(f"{NIGHTLY}.member_repo.set_personal_starters", new=AsyncMock()),
                patch(
                    f"{NIGHTLY}.suggestion_repo.propose", new=AsyncMock(return_value=MagicMock())
                ),
                patch(
                    f"{NIGHTLY}.NotificationService",
                    return_value=MagicMock(suggestions_ready=AsyncMock()),
                ),
            ],
        }

    async def _look(self, **kwargs):
        setup = self._patches(**kwargs)
        look = NightlyLook(MagicMock())
        look.thinker = setup["thinker"]
        started = [p.start() for p in setup["patches"]]
        try:
            made = await look.look(ORG, USER)
        finally:
            for p in setup["patches"]:
                p.stop()
        names = [
            "get",
            "member",
            "last",
            "requests",
            "notes",
            "routines",
            "connections",
            "update",
            "starters",
            "propose",
            "notify",
        ]
        return made, setup["thinker"], dict(zip(names, started, strict=True))

    async def test_a_quiet_week_with_first_messages_written_costs_nothing(self):
        made, thinker, _ = await self._look(starters=["a"], last=datetime.now(UTC), requests=())

        assert made == 0
        thinker.think.assert_not_awaited()

    @pytest.mark.parametrize("case", ["gone", "suspended", "not-a-member", "no-starter"])
    async def test_nobody_who_cannot_be_reached_is_read(self, case):
        made, thinker, _ = (
            await self._look(
                user=_user(is_active=case != "suspended"),
                member=case != "not-a-member",
                agent=case != "no-starter",
            )
            if case != "gone"
            else (0, None, None)
        )
        if case == "gone":
            with (
                patch(f"{NIGHTLY}.user_repo.get_by_id", new=AsyncMock(return_value=None)),
                patch(f"{NIGHTLY}.member_repo.get_active", new=AsyncMock(return_value=None)),
            ):
                made = await NightlyLook(MagicMock()).look(ORG, USER)
        else:
            thinker.think.assert_not_awaited()
        assert made == 0

    async def test_a_model_that_could_not_answer_proposes_nothing(self):
        made, _, mocks = await self._look(
            reading=None, requests=[MagicMock(content="x", created_at=datetime.now(UTC))]
        )

        assert made == 0
        mocks["propose"].assert_not_awaited()

    async def test_what_it_read_becomes_first_messages_and_proposals_in_their_language(self):
        reading = NightlyReading(
            repeats=[
                RepeatedRequest(
                    title="Raport",
                    why="3x",
                    prompt="Raport sprzedaży",
                    cron="0 7 * * 1",
                    as_agent=False,
                ),
                RepeatedRequest(
                    title="Agent", why="2x", prompt="Odpowiadaj klientom", as_agent=True
                ),
            ],
            profile=ProfileUpdate(
                job_title="Head of sales",
                about=None,
                working_hours=WorkingHours(days=[1, 2, 3, 4, 5], start="09:00", end="17:00"),
                title="Zapisać rolę?",
                why="Notatka mówi",
            ),
            starters=["  Pokaż mój pipeline  ", "", "Plan na dziś"],
            role_pack="sales",
            role_pack_title="Pakiet sprzedaży",
        )
        made, _, mocks = await self._look(
            reading=reading, requests=[MagicMock(content="Raport", created_at=datetime.now(UTC))]
        )

        assert made == 4
        # Kept on the membership: they come from this organization's week (Codex on #2324).
        assert mocks["starters"].await_args.kwargs["starters"] == [
            "Pokaż mój pipeline",
            "Plan na dziś",
        ]
        proposed = [call.kwargs for call in mocks["propose"].await_args_list]
        assert [p["kind"] for p in proposed] == ["routine", "agent", "profile", "role_pack"]
        assert proposed[0]["payload"] == {"prompt": "Raport sprzedaży", "cron": "0 7 * * 1"}
        assert proposed[1]["payload"] == {"request": "Odpowiadaj klientom"}
        assert proposed[2]["payload"]["job_title"] == "Head of sales"
        assert "about" not in proposed[2]["payload"]
        assert proposed[3]["payload"] == {"pack": "sales"}
        # Keys are stable per proposal, so the same one tomorrow is the same key.
        assert proposed[0]["dedupe_key"].startswith("routine:")
        mocks["notify"].return_value.suggestions_ready.assert_awaited_once()

    async def test_a_profile_it_already_has_and_an_unknown_pack_propose_nothing(self):
        reading = NightlyReading(
            profile=ProfileUpdate(job_title="CFO", title="t", why="w"),
            role_pack="astronaut",
        )
        made, _, mocks = await self._look(user=_user(job_title="CFO"), reading=reading)

        assert made == 0
        mocks["propose"].assert_not_awaited()
        mocks["update"].assert_not_awaited()
        mocks["notify"].return_value.suggestions_ready.assert_not_awaited()

    async def test_a_proposal_already_made_does_not_count_as_new(self):
        reading = NightlyReading(role_pack="sales")
        setup = self._patches(reading=reading)
        look = NightlyLook(MagicMock())
        look.thinker = setup["thinker"]
        for p in setup["patches"]:
            p.start()
        try:
            with patch(f"{NIGHTLY}.suggestion_repo.propose", new=AsyncMock(return_value=None)):
                assert await look.look(ORG, USER) == 0
        finally:
            for p in setup["patches"]:
                p.stop()

    @pytest.mark.parametrize(
        ("last", "due"),
        [(None, True), (timedelta(hours=21), True), (timedelta(hours=2), False)],
    )
    async def test_a_person_is_due_once_most_of_a_day_has_passed(self, last, due):
        now = datetime.now(UTC)
        with patch(
            f"{NIGHTLY}.agent_run_repo.last_proactive_run_at",
            new=AsyncMock(return_value=None if last is None else now - last),
        ):
            assert await NightlyLook(MagicMock()).due(ORG, USER, now=now) is due


class TestTheSweep:
    @pytest.mark.parametrize(
        ("local", "due"),
        [
            # Monday 00:30 is not the tail of Monday 23:00: Sunday is not a day.
            (datetime(2026, 10, 19, 0, 30, tzinfo=UTC), False),
            (datetime(2026, 10, 19, 23, 30, tzinfo=UTC), True),
            # Tuesday 01:30 is the tail of Monday's 23:00.
            (datetime(2026, 10, 20, 1, 30, tzinfo=UTC), True),
            (datetime(2026, 10, 20, 2, 0, tzinfo=UTC), False),
            # Saturday 01:00 is the tail of Friday's 23:00; Saturday 23:00 is no day.
            (datetime(2026, 10, 24, 1, 0, tzinfo=UTC), True),
            (datetime(2026, 10, 24, 23, 30, tzinfo=UTC), False),
        ],
    )
    def test_a_late_hour_is_its_own_day_not_the_next_mornings(self, local, due):
        """Codex on #2324: an hour compared modulo 24 read Monday's first minutes
        as Monday's 23:00 window, and ran the look before the weekend was over."""
        candidate = SweepCandidate(
            organization_id=ORG,
            user_id=USER,
            time_zone="UTC",
            working_hours=None,
            days=[1, 2, 3, 4, 5],
            hour=23,
            timing="fixed",
        )

        assert _its_time(candidate, local) is due

    async def test_each_person_is_queued_at_the_organizations_hour_in_their_own_zone(self):
        # Wednesday 03:30 UTC: 05:30 in Warsaw (summer), 23:30 Tuesday in New York,
        # 03:30 in UTC.
        now = datetime(2026, 7, 1, 3, 30, tzinfo=UTC)
        warsaw, new_york, utc, rested, weekend, early, late = (uuid.uuid4() for _ in range(7))

        def candidate(user_id, zone, *, days=(1, 2, 3, 4, 5), timing="fixed", hours=None):
            return SweepCandidate(
                organization_id=ORG,
                user_id=user_id,
                time_zone=zone,
                working_hours=hours,
                days=list(days),
                hour=5,
                timing=timing,
            )

        candidates = [
            candidate(warsaw, "Europe/Warsaw"),
            candidate(new_york, "America/New_York"),
            candidate(utc, None),
            candidate(rested, "Europe/Warsaw"),
            # Not one of the organization's days.
            candidate(weekend, "Europe/Warsaw", days=(6, 7)),
            # An hour before a 06:30 start is the 05:00 hour; before a 10:00 one, 09:00.
            candidate(
                early,
                "Europe/Warsaw",
                timing="before_work",
                hours={"days": [1, 2, 3, 4, 5], "start": "06:30", "end": "15:00"},
            ),
            candidate(
                late,
                "Europe/Warsaw",
                timing="before_work",
                hours={"days": [1, 2, 3, 4, 5], "start": "10:00", "end": "18:00"},
            ),
        ]
        enqueue = AsyncMock()

        async def due(_self, _org, user_id, *, now):
            return user_id != rested

        # The briefing keeps the same hour, and owes nothing to the night's look
        # having run: somebody looked at yesterday still has findings to hear.
        briefed = [
            candidate(rested, "Europe/Warsaw"),
            candidate(weekend, "Europe/Warsaw", days=(6,)),
        ]
        with (
            patch(f"{FACADE}.member_repo.sweep_candidates", new=AsyncMock(return_value=candidates)),
            patch(f"{FACADE}.member_repo.briefing_candidates", new=AsyncMock(return_value=briefed)),
            patch.object(NightlyLook, "due", new=due),
            patch(f"{FACADE}.enqueue", new=enqueue),
        ):
            queued = await ProactiveService(MagicMock()).sweep(now=now)

        assert queued == 3
        queued_as = {(call.args[1].kind, call.args[2].user_id) for call in enqueue.await_args_list}
        assert queued_as == {
            (THINK_FOR_PERSON.kind, warsaw),
            (THINK_FOR_PERSON.kind, early),
            (BRIEF_PERSON.kind, rested),
        }
        # A look or briefing still queued at the next sweep is not queued twice.
        keys = [call.kwargs["dedupe_key"] for call in enqueue.await_args_list]
        assert len(set(keys)) == 3 and all(str(ORG) in key for key in keys)
        assert all(call.kwargs["dedupe_active"] for call in enqueue.await_args_list)

    async def test_a_role_pack_and_a_welcome_are_queued_not_done_in_the_request(self):
        enqueue = AsyncMock()
        with patch(f"{FACADE}.enqueue", new=enqueue):
            service = ProactiveService(MagicMock())
            await service.queue_role_pack(ORG, USER, "sales")
            await service.queue_welcome(ORG, USER)

        (_, pack_task, pack_payload), (_, welcome_task, welcome_payload) = (
            call.args for call in enqueue.await_args_list
        )
        assert pack_task is INSTALL_ROLE_PACK and pack_payload.pack_id == "sales"
        # Codex on #2324: a double click must not install the pack twice.
        pack_call = enqueue.await_args_list[0].kwargs
        assert pack_call["dedupe_key"] == f"role-pack:{ORG}:{USER}:sales"
        assert pack_call["dedupe_active"] is True
        assert welcome_task is WELCOME_MEMBER and welcome_payload.user_id == USER

    async def test_the_worker_side_hands_each_job_to_its_module(self):
        service = ProactiveService(MagicMock())
        with (
            patch.object(NightlyLook, "look", new=AsyncMock(return_value=2)),
            patch(f"{PACK}.install", new=AsyncMock(return_value=3)),
            patch(f"{WELCOME}.welcome", new=AsyncMock(return_value=1)),
        ):
            assert await service.think_for(ORG, USER) == 2
            assert await service.install_role_pack(ORG, USER, "sales") == 3
            assert await service.welcome(ORG, USER) == 1


class TestRolePacks:
    def test_every_pack_installs_only_schedule_templates_it_names(self):
        for role_pack in PACKS:
            templates = routines_of(role_pack)
            assert [template.key for template in templates] == list(role_pack.routines)
            assert all(template.trigger_type == "schedule" for template in templates)
        assert pack("nobody") is None

    async def test_installing_makes_each_routine_once_as_the_person(self):
        sales = pack("sales")
        assert sales is not None
        already = routines_of(sales)[0].prompt
        create = AsyncMock()
        with (
            patch(
                f"{PACK}.member_repo.get_active",
                new=AsyncMock(return_value=MagicMock(role="member")),
            ),
            patch.object(ProactiveThinker, "starter_agent", new=AsyncMock(return_value=_agent())),
            patch(
                f"{PACK}.agent_trigger_repo.prompts_created_by",
                new=AsyncMock(return_value=[already]),
            ),
            patch(f"{PACK}.AgentTriggerService", return_value=MagicMock(create=create)),
        ):
            made = await _role_pack.install(MagicMock(), ORG, USER, "sales")

        assert made == len(sales.routines) - 1
        ctx, _agent_id, data = create.await_args.args
        assert ctx.user_id == USER
        assert data.trigger_type == "schedule"
        assert data.prompt != already

    @pytest.mark.parametrize("missing", ["pack", "member", "agent"])
    async def test_nothing_is_installed_for_an_unknown_pack_a_leaver_or_no_starter(self, missing):
        with (
            patch(
                f"{PACK}.member_repo.get_active",
                new=AsyncMock(
                    return_value=None if missing == "member" else MagicMock(role="member")
                ),
            ),
            patch.object(
                ProactiveThinker,
                "starter_agent",
                new=AsyncMock(return_value=None if missing == "agent" else _agent()),
            ),
        ):
            pack_id = "nobody" if missing == "pack" else "sales"
            assert await _role_pack.install(MagicMock(), ORG, USER, pack_id) == 0


def _bot(platform: str, *, active: bool = True) -> MagicMock:
    bot = MagicMock(id=uuid.uuid4(), platform=platform, is_active=active, api_base_url=None)
    bot.name = f"{platform} bot"
    return bot


class TestTheWelcome:
    async def _welcome(
        self,
        bots_by_platform,
        adapters,
        *,
        user=None,
        shared=(),
        enabled=True,
        words=None,
        member=True,
    ):
        async def by_platform(_db, platform, *, organization_id):
            return bots_by_platform.get(platform, [])

        organization = MagicMock(welcome_dm_enabled=enabled, welcome_dm_text=words)
        organization.name = "Acme"

        class Fake:
            def __init__(self, platform):
                self.platform = platform

            async def __aenter__(self):
                return adapters[self.platform]

            async def __aexit__(self, *_):
                return False

        with (
            patch(
                f"{WELCOME}.user_repo.get_by_id",
                new=AsyncMock(
                    return_value=user
                    or SimpleNamespace(email="ada@acme.com", locale="de", is_active=True)
                ),
            ),
            patch(
                f"{WELCOME}.organization_repo.get_by_id", new=AsyncMock(return_value=organization)
            ),
            patch(
                f"{WELCOME}.member_repo.get_active",
                new=AsyncMock(return_value=MagicMock() if member else None),
            ),
            patch(f"{WELCOME}.channel_bot_repo.get_by_platform", new=by_platform),
            patch(
                f"{WELCOME}.teams_conversation_repo.list_shared",
                new=AsyncMock(return_value=list(shared)),
            ),
            patch(f"{WELCOME}.unseal_bot_token", return_value="token"),
            patch(f"{WELCOME}._adapter", new=Fake),
        ):
            return await _welcome.welcome(MagicMock(), ORG, USER)

    async def test_every_connected_platform_that_knows_them_greets_them_in_their_language(self):
        slack, teams = _bot("slack"), _bot("teams")
        adapters = {
            "slack": MagicMock(welcome=AsyncMock(return_value=True)),
            "teams": MagicMock(welcome=AsyncMock(return_value=True)),
        }
        shared = [MagicMock(bot_id=teams.id, key="k1"), MagicMock(bot_id=uuid.uuid4(), key="other")]

        greeted = await self._welcome(
            {"slack": [slack, _bot("slack", active=False)], "teams": [teams]},
            adapters,
            shared=shared,
        )

        assert greeted == 2
        args = adapters["slack"].welcome.await_args
        assert args.args[1] == "ada@acme.com"
        assert args.args[2].startswith("Willkommen bei Acme! Ich bin slack bot")
        # Teams looks people up only in the conversations its own bot is in.
        assert adapters["teams"].welcome.await_args.kwargs["places"] == ["k1"]

    async def test_nobody_is_greeted_where_the_organization_has_not_turned_it_on(self):
        adapters = {"slack": MagicMock(welcome=AsyncMock(return_value=True))}

        assert await self._welcome({"slack": [_bot("slack")]}, adapters, enabled=False) == 0
        adapters["slack"].welcome.assert_not_awaited()

    async def test_somebody_removed_before_the_greeting_went_out_is_not_greeted(self):
        """Codex on #2324: the greeting is queued when they join and sent later."""
        adapters = {"slack": MagicMock(welcome=AsyncMock(return_value=True))}

        assert await self._welcome({"slack": [_bot("slack")]}, adapters, member=False) == 0
        adapters["slack"].welcome.assert_not_awaited()

    async def test_the_organizations_own_words_are_said_with_only_its_names_filled_in(self):
        """An administrator's text is not a format string: a stray brace in it, or
        a placeholder reaching for an attribute, is said as written."""
        adapters = {"slack": MagicMock(welcome=AsyncMock(return_value=True))}

        await self._welcome(
            {"slack": [_bot("slack")]},
            adapters,
            words="Hi from {bot} at {organization} {braces} {bot.__class__}: {url}",
        )

        said = adapters["slack"].welcome.await_args.args[2]
        assert said.startswith("Hi from slack bot at Acme {braces} {bot.__class__}: http")

    async def test_one_platform_failing_does_not_cost_the_others_their_greeting(self):
        adapters = {
            "slack": MagicMock(welcome=AsyncMock(side_effect=httpx.ConnectError("down"))),
            "mattermost": MagicMock(welcome=AsyncMock(return_value=True)),
        }

        greeted = await self._welcome(
            {"slack": [_bot("slack")], "mattermost": [_bot("mattermost")]}, adapters
        )

        assert greeted == 1

    async def test_nobody_is_greeted_without_bots_an_account_or_an_organization(self):
        assert await self._welcome({}, {}) == 0
        assert (
            await self._welcome(
                {"slack": [_bot("slack")]},
                {"slack": MagicMock(welcome=AsyncMock(return_value=True))},
                user=SimpleNamespace(email="x@acme.com", locale=None, is_active=False),
            )
            == 0
        )

    async def test_the_process_adapter_is_used_and_a_borrowed_one_is_closed(self):
        registered = MagicMock()
        with patch(f"{WELCOME}.get_adapter", return_value=registered):
            async with _welcome._adapter("slack") as adapter:
                assert adapter is registered

        closes = AsyncMock()
        with (
            patch(f"{WELCOME}.get_adapter", side_effect=KeyError("slack")),
            patch("app.services.channels.slack.SlackAdapter.aclose", new=closes),
        ):
            async with _welcome._adapter("slack") as adapter:
                assert adapter.platform == "slack"
        closes.assert_awaited_once()

        mattermost_close = AsyncMock()
        with (
            patch(f"{WELCOME}.get_adapter", side_effect=KeyError("mattermost")),
            patch(
                "app.services.channels.mattermost.MattermostAdapter.aclose", new=mattermost_close
            ),
        ):
            async with _welcome._adapter("mattermost") as adapter:
                assert adapter.platform == "mattermost"
        mattermost_close.assert_awaited_once()

        with (
            patch(f"{WELCOME}.get_adapter", side_effect=KeyError("teams")),
            patch("app.services.channels.teams.teams_adapter", return_value="teams-adapter"),
        ):
            async with _welcome._adapter("teams") as adapter:
                assert adapter == "teams-adapter"

    def test_every_greeting_names_the_organization_the_bot_and_the_console(self):
        for text in _welcome.GREETING.values():
            filled = text.format(organization="O", bot="B", url="U")
            assert "O" in filled and "B" in filled and "U" in filled


def test_suggestion_kinds_match_what_the_look_proposes():
    assert {kind.value for kind in SuggestionKind} == {
        "routine",
        "agent",
        "profile",
        "role_pack",
        "finding",
    }


@pytest.mark.parametrize("settlement_fails", [False, True])
async def test_cancellation_settles_a_paid_response_even_if_shutdown_cancels_twice(
    settlement_fails: bool,
) -> None:
    from pydantic_ai.toolsets import FunctionToolset

    entered, settling, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def read_account() -> str:
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    async def finish(*args: object, **kwargs: object) -> None:
        settling.set()
        await release.wait()
        if settlement_fails:
            raise OSError("database unavailable")

    get_slug, limits, version, profiles, create, stored = TestThinking._patches(TestModel())
    session = _session()
    with get_slug, limits, version, profiles, create as made, stored as finished:
        finished.side_effect = finish
        task = asyncio.create_task(
            ProactiveThinker(session).think(
                _ctx(),
                feature="watches",
                output_type=str,
                instructions="Read.",
                prompt="Read.",
                toolsets=[FunctionToolset([read_account])],
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 2)
            run_id = made.return_value.id
            assert any(t.get_name() == f"run-heartbeat:{run_id}" for t in asyncio.all_tasks())
            task.cancel()
            await asyncio.wait_for(settling.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    recorded = finished.await_args.kwargs
    assert recorded["status"] == RunStatus.CANCELLED.value
    assert recorded["input_tokens"] > 0 and recorded["output_tokens"] > 0
    assert recorded["cost_is_partial"] is True
    assert session.commit.await_count == (1 if settlement_fails else 2)
    assert not any(t.get_name() == f"run-heartbeat:{run_id}" for t in asyncio.all_tasks())


async def test_proactive_spend_uses_each_response_model_not_the_profile_name() -> None:
    from pydantic_ai.usage import RequestUsage

    def answer(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart("done")],
            model_name="gpt-4.1-mini",
            usage=RequestUsage(input_tokens=100, output_tokens=5),
        )

    get_slug, limits, version, profiles, create, stored = TestThinking._patches(
        FunctionModel(answer, model_name="gpt-4.1-mini")
    )
    with get_slug, limits, version, profiles, create, stored as finished:
        assert (
            await ProactiveThinker(_session()).think(
                _ctx(), feature="nightly", output_type=str, instructions="Read.", prompt="Read."
            )
            == "done"
        )
    assert finished.await_args.kwargs["cost_usd"] > 0
    assert finished.await_args.kwargs["cost_is_partial"] is False


@pytest.mark.parametrize("provider_fails", [False, True])
async def test_terminal_persistence_errors_surface_without_masking_a_provider_bug(
    provider_fails: bool,
) -> None:
    def answer(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if provider_fails:
            raise RuntimeError("provider bug")
        return ModelResponse(parts=[TextPart("done")])

    get_slug, limits, version, profiles, create, stored = TestThinking._patches(
        FunctionModel(answer)
    )
    with get_slug, limits, version, profiles, create, stored as finished:
        finished.side_effect = OSError("database unavailable")
        with pytest.raises(
            RuntimeError if provider_fails else OSError,
            match="provider bug" if provider_fails else "database unavailable",
        ):
            await ProactiveThinker(_session()).think(
                _ctx(), feature="nightly", output_type=str, instructions="Read.", prompt="Read."
            )
    assert (
        finished.await_args.kwargs["status"]
        == (RunStatus.FAILED if provider_fails else RunStatus.COMPLETED).value
    )
