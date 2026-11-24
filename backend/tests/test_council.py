"""Council review: scores, rounds, the table, and the capability around them."""

import asyncio
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.council import CouncilConfig
from app.agents.capabilities.council._capability import Council, resolve_members
from app.agents.capabilities.council._toolset import build_council_toolset
from app.agents.council import (
    CouncilMemberReview,
    CouncilReview,
    CouncilRound,
    ResolvedCouncilMember,
    parse_score,
    render_council_table,
    round_satisfied,
    run_council_round,
)
from app.agents.factory import build_agent
from app.agents.manifest import (
    MAX_RECORDED_COUNCIL_ROUNDS,
    RunRecorder,
    as_payload,
    carried_over,
)
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.exceptions import AppException
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.services.agent_runner import AgentRunnerService
from app.services.capability_contracts import probe_context

pytestmark = pytest.mark.anyio


def _member(name: str = "Claude Opus", model: Model | None = TestModel()) -> ResolvedCouncilMember:
    return ResolvedCouncilMember(name=name, provider="anthropic", model_label="Opus", model=model)


def _unavailable(name: str = "GPT Sol") -> ResolvedCouncilMember:
    return ResolvedCouncilMember(
        name=name,
        provider="openai",
        model_label="",
        model=None,
        unavailable_reason="No model resolved for this member's model profile",
    )


class TestParseScore:
    def test_plain_score(self):
        assert parse_score("Overall: 7/10") == 7

    def test_full_marks(self):
        assert parse_score("10/10, nothing to change") == 10

    def test_spaces_around_the_slash(self):
        assert parse_score("7 / 10") == 7

    def test_no_score(self):
        assert parse_score("Looks good to me") is None

    def test_above_ten_is_not_a_score(self):
        assert parse_score("11/10, suspiciously good") is None

    def test_first_of_several(self):
        assert parse_score("First pass 7/10, after fixes 9/10") == 7

    def test_seven_out_of_a_hundred_is_not_seven_out_of_ten(self):
        assert parse_score("7/100 tests passing") is None


class TestRoundSatisfied:
    def test_all_at_or_above_threshold(self):
        round_ = CouncilRound(
            round_no=1,
            reviews=[
                CouncilMemberReview(name="A", status="scored", score=8),
                CouncilMemberReview(name="B", status="scored", score=10),
            ],
        )
        assert round_satisfied(round_, 8) is True

    def test_one_below_threshold(self):
        round_ = CouncilRound(
            round_no=1,
            reviews=[
                CouncilMemberReview(name="A", status="scored", score=8),
                CouncilMemberReview(name="B", status="scored", score=7),
            ],
        )
        assert round_satisfied(round_, 8) is False

    def test_no_score_does_not_satisfy(self):
        round_ = CouncilRound(
            round_no=1,
            reviews=[
                CouncilMemberReview(name="A", status="scored", score=10),
                CouncilMemberReview(name="B", status="no_score"),
            ],
        )
        assert round_satisfied(round_, 8) is False

    def test_unavailable_does_not_satisfy(self):
        round_ = CouncilRound(
            round_no=1,
            reviews=[
                CouncilMemberReview(name="A", status="scored", score=10),
                CouncilMemberReview(name="B", status="unavailable", reason="Down"),
            ],
        )
        assert round_satisfied(round_, 8) is False

    def test_an_empty_round_satisfies_nothing(self):
        assert round_satisfied(CouncilRound(round_no=1, reviews=[]), 8) is False


class TestRenderCouncilTable:
    def test_exact_output(self):
        rounds = [
            CouncilRound(
                round_no=1,
                reviews=[
                    CouncilMemberReview(name="Claude Opus", status="scored", score=7),
                    CouncilMemberReview(name="GPT Sol", status="scored", score=8),
                    CouncilMemberReview(name="Gemini Pro", status="no_score"),
                ],
            ),
            CouncilRound(
                round_no=2,
                reviews=[
                    CouncilMemberReview(name="Claude Opus", status="scored", score=9),
                    CouncilMemberReview(name="GPT Sol", status="scored", score=10),
                    CouncilMemberReview(name="Gemini Pro", status="scored", score=9),
                ],
            ),
        ]
        assert render_council_table(rounds) == (
            "## Council review\n"
            "\n"
            "Rounds: 2\n"
            "\n"
            "| Delegate | Round 1 | Round 2 |\n"
            "| --- | --- | --- |\n"
            "| Claude Opus | 7/10 | 9/10 |\n"
            "| GPT Sol | 8/10 | 10/10 |\n"
            "| Gemini Pro | no score | 9/10 |"
        )

    def test_unavailable_reads_unavailable(self):
        rounds = [
            CouncilRound(
                round_no=1,
                reviews=[
                    CouncilMemberReview(name="GPT Sol", status="unavailable", reason="Down"),
                ],
            )
        ]
        assert "| GPT Sol | unavailable |" in render_council_table(rounds)


class TestRunCouncilRound:
    async def test_fan_out_scores_every_member(self):
        async def review_fn(member, work, context):
            return CouncilReview(score=8, findings=["Tighten the check"], summary="")

        round_ = await run_council_round(
            [_member("A"), _member("B"), _member("C")],
            "the work",
            "",
            1,
            8,
            review_fn,
        )
        assert [review.status for review in round_.reviews] == [
            "scored",
            "scored",
            "scored",
        ]
        assert [review.score for review in round_.reviews] == [8, 8, 8]
        assert round_satisfied(round_, 8) is True

    async def test_members_run_in_parallel(self):
        """Three 0.1s reviews finish well inside their sequential 0.3s."""

        async def review_fn(member, work, context):
            await asyncio.sleep(0.1)
            return CouncilReview(score=9, findings=[], summary="")

        started = time.monotonic()
        round_ = await run_council_round(
            [_member("A"), _member("B"), _member("C")],
            "the work",
            "",
            1,
            8,
            review_fn,
        )
        assert time.monotonic() - started < 0.25
        assert all(review.status == "scored" for review in round_.reviews)

    async def test_unavailable_member_is_reported_not_substituted(self):
        async def review_fn(member, work, context):
            if member.name == "B":
                raise AssertionError("an unavailable member is never reviewed")
            return CouncilReview(score=9, findings=[], summary="")

        round_ = await run_council_round(
            [_member("A"), _unavailable("B")], "the work", "", 1, 8, review_fn
        )
        assert round_.reviews[0].status == "scored"
        assert round_.reviews[1].status == "unavailable"
        assert round_.reviews[1].reason is not None
        assert round_satisfied(round_, 8) is False

    @pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
    async def test_a_failed_or_cancelled_reviewer_does_not_discard_its_sibling(self, failure):
        async def review_fn(member, work, context):
            if member.name == "B":
                raise failure("provider down")
            return CouncilReview(score=9, findings=[], summary="")

        round_ = await run_council_round(
            [_member("A"), _member("B")], "the work", "", 1, 8, review_fn
        )
        assert round_.reviews[0].status == "scored"
        assert round_.reviews[1].status == "unavailable"
        assert round_.reviews[1].reason == failure.__name__

    async def test_a_none_review_is_no_score(self):
        async def review_fn(member, work, context):
            return None

        round_ = await run_council_round([_member("A")], "the work", "", 1, 8, review_fn)
        assert round_.reviews[0].status == "no_score"
        assert round_.reviews[0].score is None

    async def test_a_score_in_the_summary_counts(self):
        async def review_fn(member, work, context):
            return CouncilReview(score=None, findings=[], summary="Solid work, 8/10 overall.")

        round_ = await run_council_round([_member("A")], "the work", "", 1, 8, review_fn)
        assert round_.reviews[0].status == "scored"
        assert round_.reviews[0].score == 8

    async def test_no_score_anywhere_is_no_score(self):
        async def review_fn(member, work, context):
            return CouncilReview(score=None, findings=["Needs work"], summary="")

        round_ = await run_council_round([_member("A")], "the work", "", 1, 8, review_fn)
        assert round_.reviews[0].status == "no_score"

    def test_a_round_survives_its_record(self):
        round_ = CouncilRound(
            round_no=2,
            reviews=[CouncilMemberReview(name="A", status="scored", score=9)],
        )
        assert CouncilRound.from_record(round_.to_record(8)) == round_


class TestResolveCouncilMembers:
    def test_rejects_configured_provider_that_disagrees_with_profile(self):
        profile_id = uuid.uuid4()
        spec = ModelRequestSpec(
            profile_id=profile_id,
            label="Claude Opus",
            provider="anthropic",
            model="claude-opus-4-1",
            params={},
            credential=ResolvedCredential(
                provider="anthropic",
                secret=ApiKeySecret(api_key=SecretStr("sk-ant-test-key")),
            ),
            fallbacks=[],
        )
        member = resolve_members(
            [{"name": "Configured OpenAI", "provider": "openai", "model_profile_id": profile_id}],
            {profile_id: spec},
        )[0]
        assert member.provider == "openai"
        assert member.model is None
        assert "does not match" in member.unavailable_reason


class TestCouncilConfig:
    def test_requires_three_members(self):
        member = {"name": "A", "provider": "anthropic", "model_profile_id": str(uuid.uuid4())}
        with pytest.raises(ValidationError, match="at least 3 items"):
            CouncilConfig.model_validate({"members": [member]})

    def test_at_most_three_members(self):
        members = [
            {"name": f"M{i}", "provider": "p", "model_profile_id": str(uuid.uuid4())}
            for i in range(4)
        ]
        with pytest.raises(ValidationError):
            CouncilConfig.model_validate({"members": members})

    def test_requires_three_distinct_providers(self):
        members = [
            {"name": f"M{i}", "provider": "anthropic", "model_profile_id": str(uuid.uuid4())}
            for i in range(3)
        ]
        with pytest.raises(ValidationError, match="three distinct providers"):
            CouncilConfig.model_validate({"members": members})

    def test_threshold_is_one_to_ten(self):
        member = [
            {"name": f"M{i}", "provider": p, "model_profile_id": str(uuid.uuid4())}
            for i, p in enumerate(("anthropic", "openai", "google"))
        ]
        with pytest.raises(ValidationError):
            CouncilConfig.model_validate({"members": member, "agreement_threshold": 0})
        with pytest.raises(ValidationError):
            CouncilConfig.model_validate({"members": member, "agreement_threshold": 11})

    def test_max_rounds_is_one_to_five(self):
        member = [
            {"name": f"M{i}", "provider": p, "model_profile_id": str(uuid.uuid4())}
            for i, p in enumerate(("anthropic", "openai", "google"))
        ]
        with pytest.raises(ValidationError):
            CouncilConfig.model_validate({"members": member, "max_rounds": 6})


class TestManifest:
    def test_council_rounds_are_in_the_payload(self):
        recorder = RunRecorder()
        recorder.council_rounds.append(
            {
                "round": 1,
                "satisfied": True,
                "reviews": [
                    {
                        "name": "A",
                        "status": "scored",
                        "score": 9,
                        "findings": [],
                        "reason": None,
                    }
                ],
            }
        )
        assert as_payload(recorder)["council_rounds"] == recorder.council_rounds

    def test_carried_over_keeps_earlier_rounds_and_caps_them(self):
        earlier = {
            "round": 1,
            "satisfied": False,
            "reviews": [],
        }
        previous = {"council_rounds": [earlier] * (MAX_RECORDED_COUNCIL_ROUNDS + 2)}
        payload = {"council_rounds": [{"round": 2, "satisfied": True, "reviews": []}]}
        merged = carried_over(previous, payload)
        assert len(merged["council_rounds"]) == MAX_RECORDED_COUNCIL_ROUNDS
        assert merged["council_rounds"][0] == earlier

    def test_carried_over_without_earlier_rounds_is_unchanged(self):
        payload = {"council_rounds": []}
        assert carried_over({}, payload) is payload


class TestCouncilTool:
    def _tool(self, members, recorder, threshold=8, max_rounds=3):
        toolset = build_council_toolset(members, recorder, threshold, max_rounds)
        return toolset.tools["run_council_review"].function

    async def test_no_members_is_a_refusal_not_a_round(self):
        recorder = RunRecorder()
        tool = self._tool([], recorder)
        result = await tool(None, "the work")
        assert "no members configured" in result
        assert recorder.council_rounds == []

    async def test_max_rounds_is_a_refusal(self):
        recorder = RunRecorder()
        recorder.council_rounds.append({"round": 1, "satisfied": False, "reviews": []})
        tool = self._tool([_member("A")], recorder, max_rounds=1)
        result = await tool(None, "the work")
        assert "No more council rounds" in result
        assert len(recorder.council_rounds) == 1

    async def test_a_scored_round_is_recorded_and_rendered(self, monkeypatch):
        async def fake_ambient(ctx, **kwargs):
            return CouncilReview(score=9, findings=["Ship it"], summary="")

        monkeypatch.setattr(
            "app.agents.capabilities.council._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        tool = self._tool([_member("A"), _member("B")], recorder)
        result = json.loads(await tool(None, "the work", "some context"))
        assert result["round"] == 1
        assert result["satisfied"] is True
        assert "## Council review" in result["table"]
        assert "| A | 9/10 |" in result["table"]
        assert len(recorder.council_rounds) == 1
        assert recorder.council_rounds[0]["satisfied"] is True

    async def test_an_unsatisfied_round_renders_its_table(self, monkeypatch):
        async def fake_ambient(ctx, **kwargs):
            return CouncilReview(score=7, findings=["Fix the check"], summary="")

        monkeypatch.setattr(
            "app.agents.capabilities.council._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        tool = self._tool([_member("A")], recorder)
        first = json.loads(await tool(None, "the work"))
        assert first["satisfied"] is False
        second = json.loads(await tool(None, "the fixed work"))
        assert second["round"] == 2
        assert "Rounds: 2" in second["table"]

    async def test_builder_with_empty_resources_reports_unavailable(self):
        """No resolved models: the tool still builds and answers, never crashes."""
        config = {
            "members": [
                {
                    "name": "Claude Opus",
                    "provider": "anthropic",
                    "model_profile_id": str(uuid.uuid4()),
                },
                {"name": "GPT", "provider": "openai", "model_profile_id": str(uuid.uuid4())},
                {"name": "Gemini", "provider": "google", "model_profile_id": str(uuid.uuid4())},
            ],
            "agreement_threshold": 8,
            "max_rounds": 3,
        }
        built = build_capabilities(
            [CapabilityBinding(capability_id="council", config=config)], resources={}
        )
        assert len(built) == 1
        assert isinstance(built[0], Council)
        toolset = built[0].get_toolset()
        assert built[0].get_toolset() is toolset
        assert isinstance(toolset, FunctionToolset)
        tools = await toolset.get_tools(probe_context(built[0]))
        assert "run_council_review" in tools
        result = json.loads(
            await toolset.tools["run_council_review"].function(probe_context(built[0]), "the work")
        )
        assert result["reviews"][0]["status"] == "unavailable"
        assert result["satisfied"] is False


class TestFactoryWiring:
    def test_build_agent_resolves_council_members_from_the_factory(self):
        profile_id = uuid.uuid4()
        spec = AgentSpec(
            name="Reviewer",
            instructions="Review things.",
            capabilities=[
                {
                    "id": "council",
                    "config": {
                        "members": [
                            {
                                "name": "Claude Opus",
                                "provider": "anthropic",
                                "model_profile_id": str(profile_id),
                            },
                            {
                                "name": "GPT",
                                "provider": "openai",
                                "model_profile_id": str(uuid.uuid4()),
                            },
                            {
                                "name": "Gemini",
                                "provider": "google",
                                "model_profile_id": str(uuid.uuid4()),
                            },
                        ],
                        "agreement_threshold": 8,
                        "max_rounds": 3,
                    },
                }
            ],
        )
        member_spec = ModelRequestSpec(
            profile_id=profile_id,
            label="Opus",
            provider="anthropic",
            model="claude-opus-4-1",
            params={},
            credential=ResolvedCredential(
                provider="anthropic",
                secret=ApiKeySecret(api_key=SecretStr("sk-ant-test-key")),
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
            council_models={profile_id: member_spec},
        )
        council = next(
            capability for capability in built.capabilities if isinstance(capability, Council)
        )
        assert len(council.members) == 3
        assert council.members[0].model is not None
        assert council.members[0].unavailable_reason is None
        assert council.recorder is built.recorder


class TestRunnerWiring:
    async def test_council_models_resolve_and_an_unresolvable_one_is_left_out(self):
        good_id = uuid.uuid4()
        gone_id = uuid.uuid4()
        spec = AgentSpec(
            name="Reviewer",
            instructions="Review things.",
            capabilities=[
                {
                    "id": "council",
                    "config": {
                        "members": [
                            {
                                "name": "A",
                                "provider": "anthropic",
                                "model_profile_id": str(good_id),
                            },
                            {
                                "name": "B",
                                "provider": "openai",
                                "model_profile_id": str(gone_id),
                            },
                            {
                                "name": "C",
                                "provider": "google",
                                "model_profile_id": str(uuid.uuid4()),
                            },
                        ]
                    },
                }
            ],
        )
        resolved = ModelRequestSpec(
            profile_id=good_id,
            label="Opus",
            provider="anthropic",
            model="claude-opus-4-1",
            params={},
            credential=ResolvedCredential(
                provider="anthropic",
                secret=ApiKeySecret(api_key=SecretStr("sk-ant-test-key")),
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
        assert await service._council_models(ctx, spec) == {good_id: resolved}

    async def test_an_invalid_council_binding_is_skipped(self):
        spec = AgentSpec(
            name="Reviewer",
            instructions="Review things.",
            capabilities=[{"id": "council", "config": {"members": []}}],
        )
        service = AgentRunnerService(MagicMock())
        service.models = MagicMock()
        service.models.resolve = AsyncMock()
        ctx = AuthContext(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            role=OrgRoleName.OWNER,
        )
        assert await service._council_models(ctx, spec) == {}
        service.models.resolve.assert_not_called()


class TestCouncilBoundaryOutcomes:
    def test_an_absent_or_skipped_delegate_never_acquires_an_invented_score(self) -> None:
        table = render_council_table(
            [
                CouncilRound(1, [CouncilMemberReview("A", "scored", 8)]),
                CouncilRound(2, [CouncilMemberReview("B", "skipped")]),
            ]
        )
        assert "| A | 8/10 | no score |" in table
        assert "| B | no score | no score |" in table

    async def test_the_first_score_in_findings_is_kept_without_rewriting_them(self) -> None:
        findings = ["Add the missing test.", "Overall 8/10.", "With that fixed, 9/10."]

        async def review(member, work, context):
            return CouncilReview(findings=findings, summary="A few changes remain.")

        round_ = await run_council_round([_member("A")], "work", "", 1, 8, review)
        assert round_.reviews[0].status == "scored"
        assert round_.reviews[0].score == 8
        assert round_.reviews[0].findings == findings

    @pytest.mark.security
    def test_a_model_that_cannot_be_built_stays_unavailable_without_using_its_fallback(
        self,
        monkeypatch,
    ) -> None:
        fallback = ModelRequestSpec(
            profile_id=uuid.uuid4(),
            label="Other provider",
            provider="openai",
            model="gpt-5.4",
            params={},
            credential=ResolvedCredential(
                provider="openai",
                secret=ApiKeySecret(api_key=SecretStr("test-only")),
            ),
            fallbacks=[],
        )
        primary = ModelRequestSpec(
            profile_id=uuid.uuid4(),
            label="Configured Claude",
            provider="anthropic",
            model="claude-sonnet-5-5",
            params={},
            credential=ResolvedCredential(
                provider="anthropic",
                secret=ApiKeySecret(api_key=SecretStr("test-only")),
            ),
            fallbacks=[fallback],
        )
        build = MagicMock(side_effect=ValueError("unsupported model"))
        monkeypatch.setattr("app.agents.capabilities.council._capability.build_model", build)
        member = resolve_members(
            [{"name": "A", "provider": "anthropic", "model_profile_id": primary.profile_id}],
            {primary.profile_id: primary},
        )[0]
        assert member.name == "A"
        assert member.provider == "anthropic"
        assert member.model_label == "Configured Claude"
        assert member.model is None
        assert member.unavailable_reason == "Its model could not be built"
        build.assert_called_once_with(primary.credential, primary.model)

    async def test_a_full_manifest_still_returns_the_new_round_without_overwriting_history(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "app.agents.capabilities.council._toolset.MAX_RECORDED_COUNCIL_ROUNDS",
            1,
        )
        review = AsyncMock(return_value=CouncilReview(score=9, findings=["Ready."]))
        monkeypatch.setattr("app.agents.capabilities.council._toolset.run_ambient_agent", review)
        earlier = CouncilRound(1, [CouncilMemberReview("A", "scored", 6)]).to_record(8)
        recorder = RunRecorder(council_rounds=[earlier])
        tool = build_council_toolset([_member("A")], recorder, 8, 3)
        result = json.loads(await tool.tools["run_council_review"].function(None, "fixed work"))
        assert result["round"] == 2
        assert result["satisfied"] is True
        assert "| A | 6/10 | 9/10 |" in result["table"]
        assert recorder.council_rounds == [earlier]
        assert review.await_count == 1
