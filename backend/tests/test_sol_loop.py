"""Sol-loop review: verdicts, findings, rounds, the ledger, and the capability."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities._ambient import AmbientCallSkipped
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.sol_loop import SolLoopConfig
from app.agents.capabilities.sol_loop._capability import SolLoop
from app.agents.capabilities.sol_loop._toolset import build_sol_loop_toolset
from app.agents.factory import build_agent
from app.agents.manifest import (
    MAX_RECORDED_SOL_LOOP_ROUNDS,
    RunRecorder,
    as_payload,
    carried_over,
)
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.sol_loop import (
    ResolvedSolLoopReviewer,
    SolLoopFinding,
    SolLoopReview,
    SolLoopRound,
    parse_findings,
    parse_verdict,
    render_sol_loop_ledger,
    round_satisfied,
    round_scope,
    run_sol_loop_round,
    stop_reason_for,
)
from app.agents.spec import AgentSpec
from app.core.exceptions import AppException
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.services.agent_runner import AgentRunnerService
from app.services.capability_contracts import probe_context

pytestmark = pytest.mark.anyio


def _reviewer(name: str = "GPT Sol", model: Model | None = TestModel()) -> ResolvedSolLoopReviewer:
    return ResolvedSolLoopReviewer(name=name, provider="openai", model_label="Sol", model=model)


def _unavailable(name: str = "GPT Sol") -> ResolvedSolLoopReviewer:
    return ResolvedSolLoopReviewer(
        name=name,
        provider="openai",
        model_label="",
        model=None,
        unavailable_reason="No model resolved for this reviewer's model profile",
    )


def _finding(finding_id: str = "S1", severity: str = "blocker", **kwargs: object) -> SolLoopFinding:
    return SolLoopFinding(id=finding_id, severity=severity, claim="Wrong check", **kwargs)  # type: ignore[arg-type]


class TestParseVerdict:
    def test_plain_verdict(self):
        assert parse_verdict("VERDICT: APPROVE") == "APPROVE"

    def test_changes(self):
        assert parse_verdict("Some prose\nVERDICT: CHANGES\nS1 [blocker] x.py:1 Bad.") == "CHANGES"

    def test_lowercase_counts(self):
        assert parse_verdict("verdict: approve") == "APPROVE"

    def test_no_verdict(self):
        assert parse_verdict("Looks good to me") is None


class TestParseFindings:
    def test_full_line(self):
        findings = parse_findings("S1 [blocker] app/x.py:12 The check is wrong. Fix: guard it.")
        assert len(findings) == 1
        assert findings[0].id == "S1"
        assert findings[0].severity == "blocker"
        assert findings[0].file == "app/x.py"
        assert findings[0].line == 12
        assert findings[0].claim == "The check is wrong."
        assert findings[0].fix == "guard it."

    def test_line_without_a_line_number(self):
        findings = parse_findings("S2 [nit] README.md Fix the typo.")
        assert findings[0].file == "README.md"
        assert findings[0].line is None
        assert findings[0].claim == "Fix the typo."

    def test_line_without_a_fix(self):
        findings = parse_findings("S3 [should] app/y.py:3 A real bug callers will hit.")
        assert findings[0].fix == ""

    def test_prose_lines_are_skipped(self):
        findings = parse_findings("VERDICT: CHANGES\nSome thinking aloud.\nS1 [nit] a.py:1 Minor.")
        assert [finding.id for finding in findings] == ["S1"]

    def test_nothing_matching_is_nothing(self):
        assert parse_findings("No findings here.") == []


class TestRoundScope:
    def test_round_one_is_full(self):
        assert round_scope(1) == "full"

    def test_later_rounds_are_changed_only(self):
        assert round_scope(2) == "changed-only"
        assert round_scope(5) == "changed-only"


class TestRoundSatisfied:
    def test_approve_with_no_findings(self):
        round_ = SolLoopRound(round_no=1, verdict="APPROVE")
        assert round_satisfied(round_) is True

    def test_approve_with_only_nits(self):
        round_ = SolLoopRound(round_no=1, verdict="APPROVE", findings=[_finding("S1", "nit")])
        assert round_satisfied(round_) is True

    def test_approve_with_a_blocker_open(self):
        round_ = SolLoopRound(round_no=1, verdict="APPROVE", findings=[_finding("S1", "blocker")])
        assert round_satisfied(round_) is False

    def test_approve_with_a_should_open(self):
        round_ = SolLoopRound(round_no=1, verdict="APPROVE", findings=[_finding("S1", "should")])
        assert round_satisfied(round_) is False

    def test_changes_is_not_satisfied(self):
        round_ = SolLoopRound(round_no=1, verdict="CHANGES", findings=[])
        assert round_satisfied(round_) is False

    def test_no_verdict_is_not_satisfied(self):
        round_ = SolLoopRound(round_no=1, verdict="no_verdict")
        assert round_satisfied(round_) is False


class TestStopReason:
    def test_approved(self):
        round_ = SolLoopRound(round_no=1, verdict="APPROVE")
        assert stop_reason_for(round_, 3) == "approved"

    def test_nits_only_stops_early(self):
        round_ = SolLoopRound(round_no=1, verdict="CHANGES", findings=[_finding("S1", "nit")])
        assert stop_reason_for(round_, 3) == "nits_only"

    @pytest.mark.security
    def test_budget_end_is_not_approval(self):
        round_ = SolLoopRound(round_no=3, verdict="CHANGES", findings=[_finding("S1", "blocker")])
        assert stop_reason_for(round_, 3) == "budget_exhausted"
        assert round_satisfied(round_) is False

    def test_more_rounds_remain_is_no_reason(self):
        round_ = SolLoopRound(round_no=1, verdict="CHANGES", findings=[_finding("S1", "blocker")])
        assert stop_reason_for(round_, 3) is None

    def test_a_disputed_finding_raised_again_is_stuck(self):
        round_ = SolLoopRound(round_no=2, verdict="CHANGES", findings=[_finding("S1", "should")])
        assert stop_reason_for(round_, 3, frozenset({"S1"})) == "stuck"

    def test_a_disputed_id_not_raised_again_is_not_stuck(self):
        round_ = SolLoopRound(round_no=2, verdict="CHANGES", findings=[_finding("S2", "should")])
        assert stop_reason_for(round_, 3, frozenset({"S1"})) is None

    def test_unavailable_reviewer(self):
        round_ = SolLoopRound(round_no=1, verdict="unavailable")
        assert stop_reason_for(round_, 3) == "reviewer_unavailable"


class TestRenderLedger:
    def test_exact_output(self):
        rounds = [
            SolLoopRound(
                round_no=1,
                scope="full",
                verdict="CHANGES",
                model="GPT Sol",
                findings=[
                    SolLoopFinding(
                        id="S1",
                        severity="blocker",
                        claim="Wrong check",
                        file="app/x.py",
                        line=12,
                        fix="Guard it",
                    )
                ],
            ),
            SolLoopRound(
                round_no=2,
                scope="changed-only",
                verdict="APPROVE",
                model="GPT Sol",
                dispositions={"S1": "agree-fixed"},
                stop_reason="approved",
            ),
        ]
        assert render_sol_loop_ledger(rounds) == (
            "## Sol-loop review\n"
            "\n"
            "Rounds: 2\n"
            "\n"
            "| Round | Scope | Verdict | Stop |\n"
            "| --- | --- | --- | --- |\n"
            "| 1 | full | CHANGES | — |\n"
            "| 2 | changed-only | APPROVE | approved |\n"
            "\n"
            "| Finding | Severity | File | Outcome |\n"
            "| --- | --- | --- | --- |\n"
            "| S1 | blocker | app/x.py | agree-fixed |\n"
            "\n"
            "Review usage: not exposed."
        )

    def test_an_unanswered_finding_reads_open(self):
        rounds = [
            SolLoopRound(
                round_no=1,
                verdict="CHANGES",
                findings=[_finding("S1", "should", file="app/y.py")],
            )
        ]
        assert "| S1 | should | app/y.py | open |" in render_sol_loop_ledger(rounds)

    def test_usage_is_reported_not_exposed(self):
        assert "not exposed" in render_sol_loop_ledger([])


class TestRunSolLoopRound:
    async def test_an_approved_round(self):
        async def review_fn(work, context):
            return SolLoopReview(verdict="APPROVE", findings=[], summary="")

        round_ = await run_sol_loop_round(_reviewer(), "the work", "", 1, 3, "full", {}, review_fn)
        assert round_.verdict == "APPROVE"
        assert round_.satisfied() is True
        assert round_.stop_reason == "approved"

    async def test_unavailable_reviewer_is_reported_not_substituted(self):
        async def review_fn(work, context):
            raise AssertionError("an unavailable reviewer is never reviewed")

        round_ = await run_sol_loop_round(
            _unavailable(), "the work", "", 1, 3, "full", {}, review_fn
        )
        assert round_.verdict == "unavailable"
        assert round_.stop_reason == "reviewer_unavailable"
        assert round_.reason is not None
        assert round_.satisfied() is False

    async def test_a_raising_review_is_unavailable_not_a_failed_round(self):
        async def review_fn(work, context):
            raise RuntimeError("provider down")

        round_ = await run_sol_loop_round(_reviewer(), "the work", "", 1, 3, "full", {}, review_fn)
        assert round_.verdict == "unavailable"
        assert round_.reason == "RuntimeError"
        assert round_.stop_reason == "reviewer_unavailable"

    @pytest.mark.security
    async def test_a_budget_cap_skip_is_unavailable_not_approval(self):
        async def review_fn(work, context):
            raise AmbientCallSkipped("The run has reached a budget cap")

        round_ = await run_sol_loop_round(_reviewer(), "the work", "", 1, 3, "full", {}, review_fn)
        assert round_.verdict == "unavailable"
        assert round_.reason == "AmbientCallSkipped"
        assert round_.stop_reason == "reviewer_unavailable"
        assert round_.satisfied() is False

    async def test_a_none_review_is_no_verdict(self):
        async def review_fn(work, context):
            return None

        round_ = await run_sol_loop_round(_reviewer(), "the work", "", 1, 3, "full", {}, review_fn)
        assert round_.verdict == "no_verdict"
        assert round_.satisfied() is False
        assert round_.stop_reason is None

    async def test_a_verdict_in_the_summary_counts(self):
        async def review_fn(work, context):
            return SolLoopReview(verdict=None, findings=[], summary="Solid work.\nVERDICT: APPROVE")

        round_ = await run_sol_loop_round(_reviewer(), "the work", "", 1, 3, "full", {}, review_fn)
        assert round_.verdict == "APPROVE"
        assert round_.satisfied() is True

    async def test_findings_in_the_summary_are_parsed(self):
        async def review_fn(work, context):
            return SolLoopReview(
                verdict=None,
                findings=[],
                summary="VERDICT: CHANGES\nS1 [blocker] app/x.py:12 Wrong. Fix: guard it.",
            )

        round_ = await run_sol_loop_round(_reviewer(), "the work", "", 1, 3, "full", {}, review_fn)
        assert round_.verdict == "CHANGES"
        assert len(round_.findings) == 1
        assert round_.findings[0].id == "S1"

    async def test_unknown_dispositions_are_dropped_not_invented(self):
        async def review_fn(work, context):
            return SolLoopReview(verdict="APPROVE", findings=[], summary="")

        round_ = await run_sol_loop_round(
            _reviewer(),
            "the work",
            "",
            2,
            3,
            "changed-only",
            {"S1": "agree-fixed", "S2": "ignored-it"},
            review_fn,
        )
        assert round_.dispositions == {"S1": "agree-fixed"}

    def test_a_round_survives_its_record(self):
        round_ = SolLoopRound(
            round_no=2,
            scope="changed-only",
            verdict="APPROVE",
            model="GPT Sol",
            findings=[_finding("S1", "nit", file="app/x.py", line=4)],
            dispositions={"S1": "decline-nit"},
            stop_reason="approved",
        )
        assert SolLoopRound.from_record(round_.to_record()) == round_


class TestResolveReviewer:
    def test_no_reviewer_configured_is_none(self):
        from app.agents.capabilities.sol_loop._capability import resolve_reviewer

        assert resolve_reviewer(None, None) is None

    def test_a_model_that_cannot_be_built_is_unavailable(self, monkeypatch):
        from app.agents.capabilities.sol_loop._capability import resolve_reviewer

        def _raise(credential, model):
            raise RuntimeError("no such provider")

        monkeypatch.setattr("app.agents.capabilities.sol_loop._capability.build_model", _raise)
        reviewer = {
            "name": "GPT Sol",
            "provider": "openai",
            "model_profile_id": uuid.uuid4(),
        }
        spec = ModelRequestSpec(
            profile_id=reviewer["model_profile_id"],
            label="Sol",
            provider="openai",
            model="gpt-5.6-sol",
            params={},
            credential=ResolvedCredential(
                provider="openai",
                secret=ApiKeySecret(api_key=SecretStr("sk-openai-test-key")),
            ),
            fallbacks=[],
        )
        resolved = resolve_reviewer(reviewer, {reviewer["model_profile_id"]: spec})
        assert resolved is not None
        assert resolved.model is None
        assert resolved.unavailable_reason == "Its model could not be built"


class TestSolLoopCapability:
    def test_the_toolset_is_built_once(self):
        sol_loop = SolLoop(reviewer=_reviewer())
        assert sol_loop.get_toolset() is sol_loop.get_toolset()

    def test_the_instructions_describe_rounds(self):
        assert "one round per call" in SolLoop().get_instructions()


class TestSolLoopConfig:
    def test_a_reviewer_is_required(self):
        with pytest.raises(ValidationError):
            SolLoopConfig.model_validate({})

    def test_max_rounds_is_one_to_five(self):
        reviewer = {
            "name": "GPT Sol",
            "provider": "openai",
            "model_profile_id": str(uuid.uuid4()),
        }
        with pytest.raises(ValidationError):
            SolLoopConfig.model_validate({"reviewer": reviewer, "max_rounds": 0})
        with pytest.raises(ValidationError):
            SolLoopConfig.model_validate({"reviewer": reviewer, "max_rounds": 6})
        assert SolLoopConfig.model_validate({"reviewer": reviewer, "max_rounds": 5})


class TestManifest:
    def test_sol_loop_rounds_are_in_the_payload(self):
        recorder = RunRecorder()
        recorder.sol_loop_rounds.append(
            {
                "round": 1,
                "scope": "full",
                "verdict": "APPROVE",
                "model": "GPT Sol",
                "findings": [],
                "dispositions": {},
                "stop_reason": "approved",
                "reason": None,
                "satisfied": True,
            }
        )
        assert as_payload(recorder)["sol_loop_rounds"] == recorder.sol_loop_rounds

    def test_carried_over_keeps_earlier_rounds_and_caps_them(self):
        earlier = {
            "round": 1,
            "scope": "full",
            "verdict": "CHANGES",
            "model": "GPT Sol",
            "findings": [],
            "dispositions": {},
            "stop_reason": None,
            "reason": None,
            "satisfied": False,
        }
        previous = {"sol_loop_rounds": [earlier] * (MAX_RECORDED_SOL_LOOP_ROUNDS + 2)}
        payload = {
            "sol_loop_rounds": [
                {
                    "round": 2,
                    "scope": "changed-only",
                    "verdict": "APPROVE",
                    "model": "GPT Sol",
                    "findings": [],
                    "dispositions": {},
                    "stop_reason": "approved",
                    "reason": None,
                    "satisfied": True,
                }
            ]
        }
        merged = carried_over(previous, payload)
        assert len(merged["sol_loop_rounds"]) == MAX_RECORDED_SOL_LOOP_ROUNDS
        assert merged["sol_loop_rounds"][0] == earlier

    def test_carried_over_without_earlier_rounds_is_unchanged(self):
        payload = {"sol_loop_rounds": []}
        assert carried_over({}, payload) is payload


class TestSolLoopTool:
    def _tool(self, reviewer, recorder, max_rounds=3):
        toolset = build_sol_loop_toolset(reviewer, recorder, max_rounds)
        return toolset.tools["run_sol_loop_review"].function

    async def test_no_reviewer_is_a_refusal_not_a_round(self):
        recorder = RunRecorder()
        tool = self._tool(None, recorder)
        result = await tool(None, "the work")
        assert "no reviewer configured" in result
        assert recorder.sol_loop_rounds == []

    async def test_max_rounds_is_a_refusal(self):
        recorder = RunRecorder()
        recorder.sol_loop_rounds.append({"round": 1, "verdict": "CHANGES"})
        tool = self._tool(_reviewer(), recorder, max_rounds=1)
        result = await tool(None, "the work")
        assert "No more sol-loop rounds" in result
        assert len(recorder.sol_loop_rounds) == 1

    async def test_an_approved_round_is_recorded_and_rendered(self, monkeypatch):
        async def fake_ambient(ctx, **kwargs):
            return SolLoopReview(verdict="APPROVE", findings=[], summary="")

        monkeypatch.setattr(
            "app.agents.capabilities.sol_loop._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        tool = self._tool(_reviewer(), recorder)
        result = json.loads(await tool(None, "the work", "some context"))
        assert result["round"] == 1
        assert result["scope"] == "full"
        assert result["verdict"] == "APPROVE"
        assert result["satisfied"] is True
        assert result["stop_reason"] == "approved"
        assert "## Sol-loop review" in result["ledger"]
        assert len(recorder.sol_loop_rounds) == 1
        assert recorder.sol_loop_rounds[0]["satisfied"] is True

    async def test_a_second_round_is_changed_only_and_records_dispositions(self, monkeypatch):
        responses = [
            SolLoopReview(
                verdict="CHANGES",
                findings=[_finding("S1", "blocker", file="app/x.py", line=12)],
                summary="",
            ),
            SolLoopReview(verdict="APPROVE", findings=[], summary=""),
        ]

        async def fake_ambient(ctx, **kwargs):
            return responses.pop(0)

        monkeypatch.setattr(
            "app.agents.capabilities.sol_loop._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        tool = self._tool(_reviewer(), recorder)
        first = json.loads(await tool(None, "the work"))
        assert first["satisfied"] is False
        assert first["stop_reason"] is None
        second = json.loads(
            await tool(
                None,
                "the fixed work",
                changed_files=["app/x.py"],
                dispositions={"S1": "agree-fixed"},
            )
        )
        assert second["round"] == 2
        assert second["scope"] == "changed-only"
        assert second["satisfied"] is True
        assert "Rounds: 2" in second["ledger"]
        assert "| S1 | blocker | app/x.py | agree-fixed |" in second["ledger"]
        assert recorder.sol_loop_rounds[1]["dispositions"] == {"S1": "agree-fixed"}
        assert recorder.sol_loop_rounds[1]["changed_files"] == ["app/x.py"]

    async def test_an_unavailable_reviewer_is_recorded_not_a_crash(self):
        recorder = RunRecorder()
        tool = self._tool(_unavailable(), recorder)
        result = json.loads(await tool(None, "the work"))
        assert result["verdict"] == "unavailable"
        assert result["satisfied"] is False
        assert result["stop_reason"] == "reviewer_unavailable"
        assert result["reason"] is not None
        assert len(recorder.sol_loop_rounds) == 1

    @pytest.mark.security
    async def test_a_budget_cap_skip_is_recorded_as_unavailable(self, monkeypatch):
        async def fake_ambient(ctx, **kwargs):
            raise AmbientCallSkipped("The run has reached a budget cap")

        monkeypatch.setattr(
            "app.agents.capabilities.sol_loop._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        tool = self._tool(_reviewer(), recorder)
        result = json.loads(await tool(None, "the work"))
        assert result["verdict"] == "unavailable"
        assert result["stop_reason"] == "reviewer_unavailable"
        assert result["reason"] == "AmbientCallSkipped"

    async def test_a_round_past_the_manifest_cap_still_renders_in_the_ledger(self, monkeypatch):
        async def fake_ambient(ctx, **kwargs):
            return SolLoopReview(verdict="CHANGES", findings=[], summary="")

        monkeypatch.setattr(
            "app.agents.capabilities.sol_loop._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        recorder.sol_loop_rounds = [
            {"round": number, "verdict": "CHANGES"} for number in range(1, 11)
        ]
        tool = self._tool(_reviewer(), recorder, max_rounds=11)
        result = json.loads(await tool(None, "the work"))
        assert result["round"] == 11
        # The manifest keeps ten; the ledger still shows the round just run.
        assert len(recorder.sol_loop_rounds) == MAX_RECORDED_SOL_LOOP_ROUNDS
        assert "Rounds: 11" in result["ledger"]

    async def test_builder_with_empty_resources_reports_unavailable(self):
        """No resolved models: the tool still builds and answers, never crashes."""
        config = {
            "reviewer": {
                "name": "GPT Sol",
                "provider": "openai",
                "model_profile_id": str(uuid.uuid4()),
            },
            "max_rounds": 3,
        }
        built = build_capabilities(
            [CapabilityBinding(capability_id="sol_loop", config=config)], resources={}
        )
        assert len(built) == 1
        assert isinstance(built[0], SolLoop)
        toolset = built[0].get_toolset()
        assert isinstance(toolset, FunctionToolset)
        tools = await toolset.get_tools(probe_context(built[0]))
        assert "run_sol_loop_review" in tools
        result = json.loads(
            await toolset.tools["run_sol_loop_review"].function(probe_context(built[0]), "the work")
        )
        assert result["verdict"] == "unavailable"
        assert result["satisfied"] is False


class TestFactoryWiring:
    def test_build_agent_resolves_the_sol_loop_reviewer_from_the_factory(self):
        profile_id = uuid.uuid4()
        spec = AgentSpec(
            name="Reviewer",
            instructions="Review things.",
            capabilities=[
                {
                    "id": "sol_loop",
                    "config": {
                        "reviewer": {
                            "name": "GPT Sol",
                            "provider": "openai",
                            "model_profile_id": str(profile_id),
                        },
                        "max_rounds": 3,
                    },
                }
            ],
        )
        reviewer_spec = ModelRequestSpec(
            profile_id=profile_id,
            label="Sol",
            provider="openai",
            model="gpt-5.6-sol",
            params={},
            credential=ResolvedCredential(
                provider="openai",
                secret=ApiKeySecret(api_key=SecretStr("sk-openai-test-key")),
            ),
            fallbacks=[],
        )
        agent_spec = ModelRequestSpec(
            profile_id=uuid.uuid4(),
            label="GPT-4.1 (prod)",
            provider="openai",
            model="gpt-4.1",
            params={},
            credential=ResolvedCredential(
                provider="openai",
                secret=ApiKeySecret(api_key=SecretStr("sk-openai-test-key")),
            ),
            fallbacks=[],
        )
        built = build_agent(
            spec,
            agent_spec,
            organization_id=uuid.uuid4(),
            sol_loop_models={profile_id: reviewer_spec},
        )
        sol_loop = next(
            capability for capability in built.capabilities if isinstance(capability, SolLoop)
        )
        assert sol_loop.reviewer is not None
        assert sol_loop.reviewer.model is not None
        assert sol_loop.reviewer.unavailable_reason is None
        assert sol_loop.recorder is built.recorder


class TestRunnerWiring:
    async def test_sol_loop_models_resolve_and_an_unresolvable_one_is_left_out(self):
        good_id = uuid.uuid4()
        gone_id = uuid.uuid4()
        good_spec = AgentSpec(
            name="Reviewer",
            instructions="Review things.",
            capabilities=[
                {
                    "id": "sol_loop",
                    "config": {
                        "reviewer": {
                            "name": "A",
                            "provider": "openai",
                            "model_profile_id": str(good_id),
                        }
                    },
                },
            ],
        )
        gone_spec = AgentSpec(
            name="Reviewer",
            instructions="Review things.",
            capabilities=[
                {
                    "id": "sol_loop",
                    "config": {
                        "reviewer": {
                            "name": "B",
                            "provider": "openai",
                            "model_profile_id": str(gone_id),
                        }
                    },
                },
            ],
        )
        resolved = ModelRequestSpec(
            profile_id=good_id,
            label="Sol",
            provider="openai",
            model="gpt-5.6-sol",
            params={},
            credential=ResolvedCredential(
                provider="openai",
                secret=ApiKeySecret(api_key=SecretStr("sk-openai-test-key")),
            ),
            fallbacks=[],
        )
        models = MagicMock()

        async def _resolve(ctx, profile_id):
            if profile_id == good_id:
                return resolved
            raise AppException(message="gone")

        models.resolve = _resolve
        service = AgentRunnerService(MagicMock())
        service.models = models
        ctx = AuthContext(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            role=OrgRoleName.OWNER,
        )
        assert await service._sol_loop_models(ctx, good_spec) == {good_id: resolved}
        assert await service._sol_loop_models(ctx, gone_spec) == {}

    async def test_an_invalid_sol_loop_binding_is_skipped(self):
        spec = AgentSpec(
            name="Reviewer",
            instructions="Review things.",
            capabilities=[{"id": "sol_loop", "config": {}}],
        )
        service = AgentRunnerService(MagicMock())
        service.models = MagicMock()
        service.models.resolve = AsyncMock()
        ctx = AuthContext(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            role=OrgRoleName.OWNER,
        )
        assert await service._sol_loop_models(ctx, spec) == {}
        service.models.resolve.assert_not_called()
