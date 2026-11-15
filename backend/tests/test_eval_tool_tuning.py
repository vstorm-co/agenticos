"""Eval-driven tool tuning: score a tool against judged cases, draft proposals (#11)."""

import json

import pytest
from pydantic import ValidationError

from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.eval_tool_tuning import EvalToolTuningConfig
from app.agents.capabilities.eval_tool_tuning._capability import EvalToolTuning
from app.agents.capabilities.eval_tool_tuning._toolset import (
    _JudgedCaseInput,
    _ToolCallInput,
    build_eval_tool_tuning_toolset,
)
from app.agents.eval_tool_tuning import (
    JudgedCase,
    ToolCallObservation,
    TuningProposal,
    classify,
    propose_tuning,
    score_tool,
    tuning_run_record,
)
from app.agents.manifest import (
    MAX_RECORDED_EVAL_TOOL_TUNING_RUNS,
    RunRecorder,
    as_payload,
    carried_over,
)
from app.schemas.run_manifest import ManifestEvalToolTuningCase

pytestmark = pytest.mark.anyio


def _case(name="case", *, passed=False, calls=(), kind="contains", value="total"):
    return JudgedCase(
        name=name,
        expectation_kind=kind,
        expectation_value=value,
        passed=passed,
        shown="the answer said nothing useful",
        tool_calls=tuple(calls),
    )


def _call(tool, *, error=None, error_type=None):
    return ToolCallObservation(tool=tool, arguments={"q": "x"}, error=error, error_type=error_type)


class TestEvalToolTuningScoring:
    def test_passed_case_is_passed_whatever_the_tool_did(self):
        scored = classify("search", _case(passed=True, calls=[_call("other")]))
        assert scored.classification == "passed"
        assert scored.passed is True

    def test_no_tool_call_is_not_called(self):
        scored = classify("search", _case())
        assert scored.classification == "not_called"
        assert "search" in scored.detail

    def test_another_tool_picked_is_wrong_tool(self):
        scored = classify("search", _case(calls=[_call("browse"), _call("fetch")]))
        assert scored.classification == "wrong_tool"
        assert scored.other_tools == ("browse", "fetch")
        assert "browse" in scored.detail

    def test_validation_error_is_bad_arguments(self):
        scored = classify(
            "search",
            _case(calls=[_call("search", error="400 bad query", error_type="ValidationError")]),
        )
        assert scored.classification == "bad_arguments"
        assert "400 bad query" in scored.detail

    @pytest.mark.parametrize(
        ("error", "error_type", "expected"),
        [
            ("request timed out", "TimeoutError", "transient"),
            ("connection refused", "ConnectionError", "transient"),
            ("429 rate limit exceeded", "RateLimitError", "transient"),
            ("HTTP 401 unauthorized", "HTTPError", "authorization"),
            ("HTTP 403 forbidden", "HTTPError", "authorization"),
            ("400 bad query", "ValidationError", "bad_arguments"),
            ("HTTP 400 bad request", "HTTPError", "unknown"),
            ("unclassified service failure", "RuntimeError", "unknown"),
        ],
    )
    def test_tool_errors_are_classified_by_failure_kind(self, error, error_type, expected):
        scored = classify(
            "search",
            _case(calls=[_call("search", error=error, error_type=error_type)]),
        )
        assert scored.classification == expected

    def test_a_transient_error_does_not_propose_parameter_changes(self):
        score = score_tool("search", [_case(calls=[_call("search", error="timeout")])])
        assert score.cases[0].classification == "transient"
        assert propose_tuning(score) == ()

    @pytest.mark.parametrize("classification", ["transient", "authorization", "unknown"])
    def test_manifest_schema_accepts_new_failure_classes(self, classification):
        case = ManifestEvalToolTuningCase(
            name="case",
            classification=classification,
            passed=False,
        )
        assert case.classification == classification

    def test_tool_clean_but_answer_missing_is_wrong_answer(self):
        scored = classify("search", _case(calls=[_call("search")], value="total"))
        assert scored.classification == "wrong_answer"
        assert scored.expectation_value == "total"

    def test_score_counts_pass_rate_and_dominant_failure(self):
        score = score_tool(
            "search",
            [
                _case("a", passed=True),
                _case("b"),
                _case("c"),
                _case("d", calls=[_call("browse")]),
            ],
        )
        assert score.tool == "search"
        assert (score.total, score.passed) == (4, 1)
        assert score.pass_rate == pytest.approx(0.25)
        assert score.dominant_failure == "not_called"

    def test_dominant_failure_breaks_ties_towards_the_tool_itself(self):
        score = score_tool(
            "search",
            [
                _case("a", calls=[_call("browse")]),
                _case("b"),
            ],
        )
        assert score.dominant_failure == "not_called"

    def test_empty_cases_score_zero_with_no_dominant_failure(self):
        score = score_tool("search", [])
        assert (score.total, score.passed, score.pass_rate) == (0, 0, 0.0)
        assert score.dominant_failure is None
        assert propose_tuning(score) == ()

    def test_unnamed_tool_and_bad_case_are_caller_errors(self):
        with pytest.raises(ValueError, match="named tool"):
            score_tool("  ", [])
        with pytest.raises(ValueError, match="Unknown expectation kind"):
            _case(kind="smells_right")
        with pytest.raises(ValueError, match="names no case"):
            _case(name=" ")
        with pytest.raises(ValueError, match="names no tool"):
            ToolCallObservation(tool=" ")
        with pytest.raises(TypeError, match="verdict is a bool"):
            JudgedCase(
                name="guess",
                expectation_kind="contains",
                expectation_value="total",
                passed="yes",  # type: ignore[arg-type]
            )

    def test_one_proposal_per_failure_class_not_per_case(self):
        score = score_tool(
            "search",
            [
                _case("a"),
                _case("b"),
                _case("c", calls=[_call("browse")]),
                _case(
                    "d",
                    calls=[
                        _call("search", error="invalid argument: q", error_type="ValidationError")
                    ],
                ),
                _case("e", calls=[_call("search")], value="total"),
            ],
        )
        proposals = propose_tuning(score)
        assert [p.kind for p in proposals] == [
            "tool_choice",
            "tool_choice",
            "tool_parameters",
            "prompt_wording",
        ]
        assert all(isinstance(p, TuningProposal) and p.status == "draft" for p in proposals)
        assert all(p.tool == "search" for p in proposals)
        # Each proposal's evidence is exactly the cases that failed that way.
        choice = [p for p in proposals if p.kind == "tool_choice"]
        assert choice[0].evidence == ("a", "b")
        assert choice[1].evidence == ("c",)
        assert next(p for p in proposals if p.kind == "tool_parameters").evidence == ("d",)
        wrong_answer = next(p for p in proposals if p.kind == "prompt_wording")
        assert wrong_answer.evidence == ("e",)
        assert "total" in wrong_answer.proposed

    def test_no_failures_drafts_nothing(self):
        score = score_tool("search", [_case("a", passed=True)])
        assert propose_tuning(score) == ()

    def test_proposals_are_drafts_with_no_apply_path(self):
        """A proposal is a draft for a human; this module offers no way to apply one."""
        import app.agents.eval_tool_tuning as tuning

        assert not hasattr(tuning, "apply_tuning")
        assert not hasattr(tuning, "apply_proposal")
        score = score_tool("search", [_case("a")])
        (proposal,) = propose_tuning(score)
        assert proposal.status == "draft"

    def test_record_is_a_plain_json_snapshot(self):
        score = score_tool("search", [_case("a", passed=True), _case("b", calls=[_call("browse")])])
        record = tuning_run_record(score, propose_tuning(score))
        assert json.loads(json.dumps(record)) == record
        assert record["tool"] == "search"
        assert (record["total"], record["passed"]) == (2, 1)
        assert record["dominant_failure"] == "wrong_tool"
        assert [c["classification"] for c in record["cases"]] == [
            "passed",
            "wrong_tool",
        ]
        assert record["proposals"][0]["status"] == "draft"
        assert record["proposals"][0]["evidence"] == ["b"]


def _cases():

    return [
        _JudgedCaseInput(
            name="total",
            expectation_kind="contains",
            expectation_value="total",
            passed=True,
            shown="The total is 42.",
            tool_calls=[_ToolCallInput(tool="search", arguments={"q": "total"})],
        ),
        _JudgedCaseInput(
            name="missing",
            expectation_kind="contains",
            expectation_value="total",
            passed=False,
            shown="No answer given.",
            tool_calls=[],
        ),
    ]


class TestEvalToolTuningTool:
    def _tool(self, recorder, max_tuning_runs=3):
        toolset = build_eval_tool_tuning_toolset(recorder, max_tuning_runs)
        return toolset.tools["record_eval_tool_tuning"].function

    async def test_a_tuning_run_is_scored_drafted_and_recorded(self):
        recorder = RunRecorder()
        tool = self._tool(recorder)
        result = json.loads(await tool(None, "search", _cases()))
        assert result["tuning_run"] == 1
        assert result["tool"] == "search"
        assert (result["total"], result["passed"]) == (2, 1)
        assert result["pass_rate"] == pytest.approx(0.5)
        assert result["dominant_failure"] == "not_called"
        assert [p["kind"] for p in result["proposals"]] == ["tool_choice"]
        assert result["proposals"][0]["status"] == "draft"
        assert "nothing was applied" in result["note"]
        assert len(recorder.eval_tool_tuning_runs) == 1
        record = recorder.eval_tool_tuning_runs[0]
        assert record["tool"] == "search"
        assert [c["classification"] for c in record["cases"]] == [
            "passed",
            "not_called",
        ]

    async def test_an_unnamed_tool_is_a_refusal_not_a_run(self):
        recorder = RunRecorder()
        tool = self._tool(recorder)
        result = await tool(None, "  ", _cases())
        assert "Name the tool" in result
        assert recorder.eval_tool_tuning_runs == []

    async def test_a_malformed_case_is_a_refusal_not_a_run(self):
        recorder = RunRecorder()
        tool = self._tool(recorder)
        bad = _JudgedCaseInput(
            name="bad",
            expectation_kind="smells_right",
            expectation_value="x",
            passed=False,
        )
        result = await tool(None, "search", [bad])
        assert "Cannot score" in result
        assert recorder.eval_tool_tuning_runs == []

    async def test_max_tuning_runs_is_a_refusal(self):
        recorder = RunRecorder()
        recorder.eval_tool_tuning_runs.append({"tool": "search"})
        tool = self._tool(recorder, max_tuning_runs=1)
        result = await tool(None, "search", _cases())
        assert "No more tuning runs" in result
        assert len(recorder.eval_tool_tuning_runs) == 1

    async def test_the_record_keeps_only_the_last_ten_runs(self):
        recorder = RunRecorder()
        recorder.eval_tool_tuning_runs = [{"tool": "search"}] * 12
        tool = self._tool(recorder, max_tuning_runs=13)
        result = json.loads(await tool(None, "search", _cases()))
        assert result["tuning_run"] == 13
        assert len(recorder.eval_tool_tuning_runs) == MAX_RECORDED_EVAL_TOOL_TUNING_RUNS
        assert recorder.eval_tool_tuning_runs[-1]["tool"] == "search"


class TestEvalToolTuningCapability:
    def test_the_toolset_is_built_once(self):
        tuning = EvalToolTuning()
        assert tuning.get_toolset() is tuning.get_toolset()

    def test_the_instructions_name_the_draft_rule(self):
        assert "drafts" in EvalToolTuning().get_instructions()
        assert "Never apply a proposal yourself" in EvalToolTuning().get_instructions()

    def test_a_missing_recorder_records_onto_a_fresh_one(self):
        tuning = EvalToolTuning()
        assert tuning.recorder.eval_tool_tuning_runs == []

    def test_the_builder_wires_the_recorder(self):
        recorder = RunRecorder()
        built = build_capabilities(
            [CapabilityBinding(capability_id="eval_tool_tuning", config={})],
            granted_scopes=frozenset(),
            resources={"eval_tool_tuning_recorder": recorder},
        )
        assert len(built) == 1
        assert isinstance(built[0], EvalToolTuning)
        assert built[0].recorder is recorder

    def test_the_builder_honours_a_configured_cap(self):
        built = build_capabilities(
            [
                CapabilityBinding(
                    capability_id="eval_tool_tuning",
                    config={"max_tuning_runs": 2},
                )
            ],
            granted_scopes=frozenset(),
            resources={},
        )
        assert len(built) == 1
        assert built[0].max_tuning_runs == 2

    def test_max_tuning_runs_is_one_to_five(self):
        with pytest.raises(ValidationError):
            EvalToolTuningConfig.model_validate({"max_tuning_runs": 0})
        with pytest.raises(ValidationError):
            EvalToolTuningConfig.model_validate({"max_tuning_runs": 6})
        assert EvalToolTuningConfig.model_validate({}).max_tuning_runs == 3


class TestEvalToolTuningManifest:
    def test_a_tuning_run_survives_its_record(self):
        recorder = RunRecorder()
        recorder.eval_tool_tuning_runs.append(
            {"tool": "search", "total": 2, "passed": 1, "cases": [], "proposals": []}
        )
        assert as_payload(recorder)["eval_tool_tuning_runs"][0]["tool"] == "search"

    def test_carried_over_keeps_earlier_tuning_runs(self):
        earlier = {"tool": "search", "total": 1, "passed": 1}
        payload = {"eval_tool_tuning_runs": [{"tool": "browse", "total": 1}]}
        merged = carried_over({"eval_tool_tuning_runs": [earlier]}, payload)
        assert merged["eval_tool_tuning_runs"] == [
            earlier,
            {"tool": "browse", "total": 1},
        ]

    def test_carried_over_without_earlier_tuning_is_unchanged(self):
        payload = {"eval_tool_tuning_runs": []}
        assert carried_over({}, payload) is payload
