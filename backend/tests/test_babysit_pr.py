"""Babysit-PR: check states, failure classification, diffs, decisions, the watcher."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from pydantic_ai.toolsets import FunctionToolset

from app.agents.babysit_pr import (
    DEFAULT_MAX_WATCH_MINUTES,
    MAX_POLL_SECONDS,
    MIN_POLL_SECONDS,
    BabysitCheck,
    BabysitEvent,
    BabysitWatcher,
    check_state,
    clamp_poll_seconds,
    classify_failure,
    decide_watch,
    diff_checks,
    now_utc,
    parse_checks,
    rate_limit_decision,
    render_report,
)
from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.babysit_pr import BabysitPrConfig
from app.agents.capabilities.babysit_pr._capability import BabysitPr
from app.agents.capabilities.babysit_pr._toolset import build_babysit_pr_toolset
from app.agents.factory import build_agent
from app.agents.manifest import (
    MAX_RECORDED_BABYSIT_PR_EVENTS,
    RunRecorder,
    as_payload,
    carried_over,
)
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret
from app.services.capability_contracts import probe_context

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _check(name="ci", status="completed", conclusion="success", detail=""):
    return BabysitCheck(name=name, status=status, conclusion=conclusion, detail=detail)


class TestCheckState:
    def test_non_completed_is_pending(self):
        for status in ("queued", "in_progress", "waiting", "requested", "pending"):
            assert check_state(status, None) == "pending"

    def test_completed_conclusions(self):
        assert check_state("completed", "success") == "passed"
        assert check_state("completed", "neutral") == "passed"
        assert check_state("completed", "failure") == "failed"
        assert check_state("completed", "timed_out") == "failed"
        assert check_state("completed", "cancelled") == "cancelled"
        assert check_state("completed", "skipped") == "skipped"
        assert check_state("completed", "action_required") == "unknown"
        assert check_state("completed", "stale") == "unknown"
        assert check_state("completed", None) == "unknown"

    def test_a_check_knows_its_state(self):
        assert _check().state == "passed"
        assert _check(status="in_progress").state == "pending"


class TestBabysitCheck:
    def test_from_dict_round_trip(self):
        check = BabysitCheck.from_dict(
            {"name": " ci ", "status": "completed", "conclusion": "failure", "detail": "x"}
        )
        assert check.name == "ci"
        assert BabysitCheck.from_dict(check.to_dict()) == check

    def test_from_dict_refuses_a_nameless_check(self):
        with pytest.raises(ValueError):
            BabysitCheck.from_dict({"status": "completed"})
        with pytest.raises(ValueError):
            BabysitCheck.from_dict({"name": "  "})

    def test_from_dict_coerces_missing_fields(self):
        check = BabysitCheck.from_dict({"name": "ci"})
        assert check.status == "queued"
        assert check.conclusion is None
        assert check.detail == ""
        assert check.url == ""

    def test_parse_checks_drops_bad_entries_and_counts_them(self):
        checks, dropped = parse_checks(
            [{"name": "ci"}, {"status": "completed"}, "not a dict", {"name": "lint"}]
        )
        assert [check.name for check in checks] == ["ci", "lint"]
        assert dropped == 2

    def test_parse_checks_refuses_a_non_list(self):
        checks, dropped = parse_checks({"name": "ci"})
        assert checks == []
        assert dropped == 1


class TestClassifyFailure:
    def test_a_non_failed_check_is_not_classified(self):
        assert classify_failure(_check()) == ("unknown", "")

    def test_a_plain_failure_is_real(self):
        kind, reason = classify_failure(_check(conclusion="failure", detail="test failed"))
        assert kind == "real"
        assert "no infrastructure signal" in reason

    def test_timed_out_is_a_flake_and_cancelled_is_not_a_failure(self):
        kind, reason = classify_failure(_check(conclusion="timed_out"))
        assert kind == "flake"
        assert "timed out" in reason
        assert _check(conclusion="cancelled").state == "cancelled"
        assert classify_failure(_check(conclusion="cancelled")) == ("unknown", "")

    @pytest.mark.parametrize(
        "detail",
        [
            "The job timed out after 3600s",
            "Connection reset by peer",
            "Lost communication with the server",
            "HTTP 503 Service Unavailable",
            "No space left on device",
            "API rate limit exceeded",
            "socket hang up while fetching",
        ],
    )
    def test_infrastructure_signals_are_flakes(self, detail):
        kind, reason = classify_failure(_check(conclusion="failure", detail=detail))
        assert kind == "flake"
        assert "infrastructure signal" in reason

    def test_action_required_is_unknown_and_blocks_green(self):
        assert classify_failure(_check(conclusion="action_required")) == ("unknown", "")
        decision, reason = decide_watch(
            [_check(conclusion="action_required")],
            head_moved=False,
            started_at=NOW,
            now=NOW,
            max_watch_minutes=240,
        )
        assert decision == "needs_attention"
        assert "human look" in reason


class TestDiffChecks:
    def test_a_new_decided_check_is_news_a_new_pending_one_is_not(self):
        events = diff_checks({}, [_check(), _check(name="lint", status="in_progress")], "abc")
        assert [event.check_name for event in events] == ["ci"]
        assert events[0].previous_state is None
        assert events[0].state == "passed"
        assert events[0].failure_kind is None

    def test_a_landing_check_is_news_a_restart_is_not(self):
        before = {"ci": _check(status="in_progress")}
        events = diff_checks(before, [_check()], "abc")
        assert len(events) == 1
        assert events[0].previous_state == "pending"
        events = diff_checks({"ci": _check()}, [_check(status="in_progress")], "abc")
        assert events == []

    def test_a_failed_check_carries_its_classification(self):
        before = {"ci": _check(status="in_progress")}
        failed = _check(conclusion="failure", detail="connection reset by peer")
        events = diff_checks(before, [failed], "abc")
        assert events[0].failure_kind == "flake"
        assert "connection reset" in events[0].reason

    def test_a_vanished_check_is_not_reported(self):
        before = {"gone": _check(name="gone"), "ci": _check()}
        events = diff_checks(before, [_check(name="ci")], "abc")
        assert events == []

    def test_an_event_round_trips(self):
        event = BabysitEvent(
            check_name="ci",
            previous_state="pending",
            state="failed",
            failure_kind="real",
            reason="no signal",
            head_sha="abc",
        )
        assert BabysitEvent.from_dict(event.to_dict()) == event

    def test_an_event_with_an_unknown_state_is_refused(self):
        with pytest.raises(ValueError):
            BabysitEvent.from_dict({"check": "ci", "state": "bogus"})


class TestDecideWatch:
    def test_failures_need_attention_with_real_and_flake_counts(self):
        checks = [
            _check(name="tests", conclusion="failure", detail="assertion failed"),
            _check(name="lint", conclusion="failure", detail="timed out"),
        ]
        decision, reason = decide_watch(
            checks, head_moved=False, started_at=NOW, now=NOW, max_watch_minutes=240
        )
        assert decision == "needs_attention"
        assert "2 check(s) failed" in reason
        assert "1 real, 1 flake" in reason

    def test_all_terminal_and_none_failed_is_green(self):
        checks = [_check(), _check(name="lint", conclusion="neutral")]
        decision, reason = decide_watch(
            checks, head_moved=False, started_at=NOW, now=NOW, max_watch_minutes=240
        )
        assert decision == "green"
        assert "latest commit" in reason

    def test_green_on_the_new_head_beats_the_head_having_moved(self):
        checks = [_check()]
        decision, _ = decide_watch(
            checks, head_moved=True, started_at=NOW, now=NOW, max_watch_minutes=240
        )
        assert decision == "green"

    def test_pending_checks_on_a_new_head_report_the_move(self):
        checks = [_check(status="in_progress")]
        decision, reason = decide_watch(
            checks, head_moved=True, started_at=NOW, now=NOW, max_watch_minutes=240
        )
        assert decision == "head_moved"
        assert "new head" in reason

    def test_no_checks_continues(self):
        decision, _ = decide_watch(
            [], head_moved=False, started_at=NOW, now=NOW, max_watch_minutes=240
        )
        assert decision == "continue"

    @pytest.mark.security
    def test_the_watch_expires_but_expiry_is_not_approval(self):
        checks = [_check(status="in_progress")]
        decision, reason = decide_watch(
            checks,
            head_moved=False,
            started_at=NOW - timedelta(minutes=241),
            now=NOW,
            max_watch_minutes=240,
        )
        assert decision == "expired"
        assert "without green" in reason

    def test_pending_checks_continue(self):
        checks = [_check(status="in_progress"), _check(name="lint")]
        decision, reason = decide_watch(
            checks, head_moved=False, started_at=NOW, now=NOW, max_watch_minutes=240
        )
        assert decision == "continue"
        assert "1 check(s) still pending" in reason

    def test_no_start_means_no_expiry(self):
        checks = [_check(status="in_progress")]
        decision, _ = decide_watch(
            checks, head_moved=False, started_at=None, now=NOW, max_watch_minutes=240
        )
        assert decision == "continue"


class TestRateLimit:
    def test_poll_gap_is_clamped(self):
        assert clamp_poll_seconds(0) == MIN_POLL_SECONDS
        assert clamp_poll_seconds(10_000) == MAX_POLL_SECONDS
        assert clamp_poll_seconds(300) == 300

    def test_room_means_watch(self):
        assert rate_limit_decision(5000, 1_000_000, 999_000, 300) == ("watch", 300)

    def test_nearly_used_up_means_wait_for_reset(self):
        action, wait = rate_limit_decision(5, 1_000_600, 1_000_000, 300)
        assert action == "wait"
        assert wait == 600

    def test_a_reset_that_already_passed_is_not_a_wait(self):
        assert rate_limit_decision(0, 999_000, 1_000_000, 300) == ("watch", 300)


class TestRenderReport:
    def test_no_change_and_continue_is_silence(self):
        assert render_report([], "continue", "still pending") == ""

    def test_events_and_decisions_render(self):
        event = BabysitEvent(
            check_name="ci",
            previous_state="pending",
            state="failed",
            failure_kind="real",
            reason="no signal",
            head_sha="abc",
        )
        report = render_report([event], "needs_attention", "1 failed")
        assert "needs_attention" in report
        assert "- ci: pending → failed (real: no signal)" in report

    def test_green_with_no_events_still_reports(self):
        assert "green" in render_report([], "green", "all green")


class TestBabysitWatcher:
    def _watcher(self):
        return BabysitWatcher()

    def test_start_claims_and_reclaiming_the_same_pr_is_a_noop(self):
        watcher = self._watcher()
        assert watcher.start("owner/repo", 7, "abc", NOW) is None
        assert watcher.active is True
        assert watcher.start("owner/repo", 7, "abc", NOW) is None
        assert watcher.started_at == NOW

    def test_start_refuses_a_second_pr_while_one_is_active(self):
        watcher = self._watcher()
        watcher.start("owner/repo", 7, "abc", NOW)
        refusal = watcher.start("owner/other", 9, "def", NOW)
        assert refusal is not None
        assert "Already watching owner/repo#7" in refusal

    def test_first_snapshot_reports_decided_checks_only(self):
        watcher = self._watcher()
        watcher.start("owner/repo", 7, "abc", NOW)
        result = watcher.check(
            "abc",
            [_check(), _check(name="lint", status="in_progress")],
            now=NOW,
            poll_interval_seconds=300,
            max_watch_minutes=DEFAULT_MAX_WATCH_MINUTES,
        )
        assert result["decision"] == "continue"
        assert len(result["events"]) == 1
        assert result["events"][0]["check"] == "ci"
        assert result["next_poll_seconds"] == 300

    def test_an_unchanged_snapshot_is_quiet(self):
        watcher = self._watcher()
        watcher.start("owner/repo", 7, "abc", NOW)
        first = watcher.check(
            "abc",
            [_check(status="in_progress")],
            now=NOW,
            poll_interval_seconds=300,
            max_watch_minutes=DEFAULT_MAX_WATCH_MINUTES,
        )
        assert first["events"] == []
        assert first["report"] == ""
        result = watcher.check(
            "abc",
            [_check(status="in_progress")],
            now=NOW,
            poll_interval_seconds=300,
            max_watch_minutes=DEFAULT_MAX_WATCH_MINUTES,
        )
        assert result["events"] == []
        assert result["report"] == ""
        assert result["decision"] == "continue"
        assert result["next_poll_seconds"] == 300

    def test_green_ends_the_watch(self):
        watcher = self._watcher()
        watcher.start("owner/repo", 7, "abc", NOW)
        watcher.check(
            "abc",
            [_check()],
            now=NOW,
            poll_interval_seconds=300,
            max_watch_minutes=DEFAULT_MAX_WATCH_MINUTES,
        )
        assert watcher.active is False

    def test_a_new_head_reports_the_move(self):
        watcher = self._watcher()
        watcher.start("owner/repo", 7, "abc", NOW)
        watcher.check(
            "abc",
            [_check(status="in_progress")],
            now=NOW,
            poll_interval_seconds=300,
            max_watch_minutes=DEFAULT_MAX_WATCH_MINUTES,
        )
        result = watcher.check(
            "def",
            [_check(status="in_progress")],
            now=NOW,
            poll_interval_seconds=300,
            max_watch_minutes=DEFAULT_MAX_WATCH_MINUTES,
        )
        assert result["head_moved"] is True
        assert result["decision"] == "head_moved"

    def test_expiry_ends_the_watch(self):
        watcher = self._watcher()
        watcher.start("owner/repo", 7, "abc", NOW - timedelta(minutes=241))
        result = watcher.check(
            "abc",
            [_check(status="in_progress")],
            now=NOW,
            poll_interval_seconds=300,
            max_watch_minutes=DEFAULT_MAX_WATCH_MINUTES,
        )
        assert result["decision"] == "expired"
        assert watcher.active is False

    def test_stop_ends_the_watch_and_says_so(self):
        watcher = self._watcher()
        watcher.start("owner/repo", 7, "abc", NOW)
        stopped = watcher.stop("ready")
        assert stopped["stopped"] is True
        assert stopped["reason"] == "ready"
        assert watcher.active is False
        assert watcher.stop("again")["stopped"] is False

    def test_now_utc_is_utc(self):
        assert now_utc().tzinfo is UTC


class TestBabysitPrCapability:
    def test_the_toolset_is_built_once(self):
        babysit = BabysitPr()
        assert babysit.get_toolset() is babysit.get_toolset()

    def test_the_instructions_describe_watching_only(self):
        instructions = BabysitPr().get_instructions()
        assert "Only the thread that owns the PR watches it" in instructions
        assert "Never merge" in instructions


class TestBabysitPrConfig:
    def test_empty_config_takes_the_defaults(self):
        config = BabysitPrConfig.model_validate({})
        assert config.poll_interval_seconds == 300
        assert config.max_watch_minutes == 240

    def test_poll_interval_is_sixty_to_eighteen_hundred(self):
        with pytest.raises(ValidationError):
            BabysitPrConfig.model_validate({"poll_interval_seconds": 59})
        with pytest.raises(ValidationError):
            BabysitPrConfig.model_validate({"poll_interval_seconds": 1801})
        assert BabysitPrConfig.model_validate({"poll_interval_seconds": 60})
        assert BabysitPrConfig.model_validate({"poll_interval_seconds": 1800})

    def test_max_watch_is_thirty_to_fourteen_forty(self):
        with pytest.raises(ValidationError):
            BabysitPrConfig.model_validate({"max_watch_minutes": 29})
        with pytest.raises(ValidationError):
            BabysitPrConfig.model_validate({"max_watch_minutes": 1441})
        assert BabysitPrConfig.model_validate({"max_watch_minutes": 1440})


class TestManifest:
    def test_babysit_pr_events_are_in_the_payload(self):
        recorder = RunRecorder()
        recorder.babysit_pr_events.append({"check": "ci", "state": "failed"})
        assert as_payload(recorder)["babysit_pr_events"] == recorder.babysit_pr_events

    def test_carried_over_caps_events_and_is_unchanged_without_them(self):
        earlier = {"check": "ci", "state": "failed"}
        previous = {"babysit_pr_events": [earlier] * 60}
        payload = {"babysit_pr_events": []}
        merged = carried_over(previous, payload)
        assert len(merged["babysit_pr_events"]) == MAX_RECORDED_BABYSIT_PR_EVENTS
        assert merged["babysit_pr_events"][0] == earlier
        payload = {"babysit_pr_events": []}
        assert carried_over({}, payload) is payload


def _snapshot(name="ci", status="completed", conclusion="success", detail=""):
    return {"name": name, "status": status, "conclusion": conclusion, "detail": detail}


class TestBabysitPrTool:
    def _toolset(self, recorder=None, poll=300, max_watch=240):
        recorder = recorder if recorder is not None else RunRecorder()
        return build_babysit_pr_toolset(BabysitWatcher(), recorder, poll, max_watch), recorder

    def _check(self, toolset):
        return toolset.tools["babysit_pr_check"].function

    async def test_a_snapshot_is_classified_and_recorded(self):
        toolset, recorder = self._toolset()
        result = json.loads(
            await self._check(toolset)(
                None, "owner/repo", 7, "abc", [_snapshot(), _snapshot("lint", "in_progress")]
            )
        )
        assert result["decision"] == "continue"
        assert len(result["events"]) == 1
        assert result["events"][0]["check"] == "ci"
        assert len(recorder.babysit_pr_events) == 1
        assert recorder.babysit_pr_events[0]["decision"] == "continue"
        assert result["dropped_checks"] == 0

    async def test_a_bad_repo_pr_or_head_is_a_refusal(self):
        toolset, recorder = self._toolset()
        check = self._check(toolset)
        assert "owner/name" in await check(None, "norepo", 7, "abc", [])
        assert "owner/name" in await check(None, "", 7, "abc", [])
        assert "1 or more" in await check(None, "owner/repo", 0, "abc", [])
        assert "head SHA" in await check(None, "owner/repo", 7, "  ", [])
        assert recorder.babysit_pr_events == []

    async def test_a_second_pr_is_refused_while_one_is_active(self):
        toolset, _ = self._toolset()
        check = self._check(toolset)
        await check(None, "owner/repo", 7, "abc", [])
        refusal = await check(None, "owner/other", 9, "def", [])
        assert "Already watching owner/repo#7" in refusal

    async def test_nameless_entries_are_dropped_and_counted(self):
        toolset, recorder = self._toolset()
        result = json.loads(
            await self._check(toolset)(
                None, "owner/repo", 7, "abc", [_snapshot(), {"status": "completed"}]
            )
        )
        assert result["dropped_checks"] == 1
        assert len(recorder.babysit_pr_events) == 1

    async def test_dropped_check_prevents_green_decision(self):
        toolset, _ = self._toolset()
        result = json.loads(
            await self._check(toolset)(
                None, "owner/repo", 7, "abc", [_snapshot(), {"status": "completed"}]
            )
        )
        assert result["dropped_checks"] == 1
        assert result["decision"] == "needs_attention"
        assert "state is unknown" in result["reason"]

    async def test_the_manifest_keeps_fifty_events(self):
        recorder = RunRecorder()
        recorder.babysit_pr_events = [{"check": f"old-{n}", "state": "passed"} for n in range(49)]
        toolset, _ = self._toolset(recorder)
        result = json.loads(
            await self._check(toolset)(
                None,
                "owner/repo",
                7,
                "abc",
                [_snapshot("new-a"), _snapshot("new-b")],
            )
        )
        assert len(result["events"]) == 2
        assert len(recorder.babysit_pr_events) == MAX_RECORDED_BABYSIT_PR_EVENTS

    async def test_rate_limit_watch_wait_and_refusal(self):
        toolset, _ = self._toolset()
        rate_limit = toolset.tools["babysit_pr_rate_limit"].function
        watch = json.loads(await rate_limit(None, 5000, 1_000_000))
        assert watch["action"] == "watch"
        assert watch["seconds"] == 300
        wait = json.loads(await rate_limit(None, 5, 1_800_000_000))
        assert wait["action"] == "wait"
        assert wait["seconds"] > 0
        assert "remaining calls" in await rate_limit(None, -1, 1_000_000)
        assert "remaining calls" in await rate_limit(None, 5, -1)

    async def test_stop_confirms_and_says_when_nothing_is_active(self):
        toolset, _ = self._toolset()
        stop = toolset.tools["babysit_pr_stop"].function
        assert "No watch is active" in await stop(None)
        check = self._check(toolset)
        await check(None, "owner/repo", 7, "abc", [])
        assert "Stopped watching owner/repo#7: ready." in await stop(None, "ready")


class TestBuilder:
    async def test_builder_with_empty_resources_still_builds_and_answers(self):
        built = build_capabilities(
            [CapabilityBinding(capability_id="babysit_pr", config={})], resources={}
        )
        assert len(built) == 1
        assert isinstance(built[0], BabysitPr)
        assert built[0].poll_interval_seconds == 300
        toolset = built[0].get_toolset()
        assert isinstance(toolset, FunctionToolset)
        tools = await toolset.get_tools(probe_context(built[0]))
        assert {"babysit_pr_check", "babysit_pr_rate_limit", "babysit_pr_stop"} <= set(tools)
        result = json.loads(
            await toolset.tools["babysit_pr_check"].function(
                probe_context(built[0]), "owner/repo", 7, "abc", [_snapshot()]
            )
        )
        assert result["decision"] == "green"


class TestFactoryWiring:
    def test_build_agent_gives_babysit_pr_the_run_recorder(self):
        spec = AgentSpec(
            name="Watcher",
            instructions="Watch things.",
            capabilities=[{"id": "babysit_pr", "config": {}}],
        )
        agent_spec = ModelRequestSpec(
            profile_id=uuid.uuid4(),
            label="GPT-4.1 (prod)",
            provider="openai",
            model="gpt-4.1",
            params={},
            credential=ResolvedCredential(
                provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
            ),
            fallbacks=[],
        )
        built = build_agent(spec, agent_spec, organization_id=uuid.uuid4())
        babysit = next(
            capability for capability in built.capabilities if isinstance(capability, BabysitPr)
        )
        assert babysit.recorder is built.recorder
