"""Burst mode: the split, the parallel fan-out, and the merge."""

import asyncio
import json

import pytest
from pydantic import ValidationError
from pydantic_ai.toolsets import FunctionToolset

from app.agents.burst import (
    MIN_SUBTASKS,
    BurstOutcome,
    BurstSubtask,
    BurstSubtaskAnswer,
    BurstSubtaskResult,
    make_subtasks,
    merge_burst,
    render_burst_summary,
    run_burst,
    validate_subtasks,
)
from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.burst import BurstConfig
from app.agents.capabilities.burst._capability import Burst
from app.agents.capabilities.burst._toolset import build_burst_toolset
from app.agents.manifest import (
    MAX_RECORDED_BURSTS,
    RunRecorder,
    as_payload,
    carried_over,
)
from app.services.capability_contracts import probe_context

pytestmark = pytest.mark.anyio


def _subtask(index: int = 1, prompt: str = "Do the first part.") -> BurstSubtask:
    return BurstSubtask(id=f"B{index}", title=f"Part {index}", prompt=prompt)


def _completed(index: int = 1, result: str = "Done.") -> BurstSubtaskResult:
    return BurstSubtaskResult(
        id=f"B{index}", title=f"Part {index}", status="completed", result=result
    )


def _failed(index: int = 1, reason: str = "ValueError") -> BurstSubtaskResult:
    return BurstSubtaskResult(id=f"B{index}", title=f"Part {index}", status="failed", reason=reason)


class TestValidateSubtasks:
    def test_valid_split(self):
        assert validate_subtasks(["First part.", "Second part."], 3) == []

    def test_one_subtask_is_not_a_burst(self):
        errors = validate_subtasks(["Only one part."], 3)
        assert len(errors) == 1
        assert "at least 2" in errors[0]

    def test_empty_split_is_not_a_burst(self):
        errors = validate_subtasks([], 3)
        assert len(errors) == 1
        assert "at least 2" in errors[0]

    def test_too_many_subtasks(self):
        errors = validate_subtasks(["One.", "Two.", "Three.", "Four."], 3)
        assert len(errors) == 1
        assert "at most 3" in errors[0]

    def test_blank_subtask(self):
        errors = validate_subtasks(["First part.", "   "], 3)
        assert len(errors) == 1
        assert "Subtask 2 is empty" in errors[0]

    def test_duplicate_subtask(self):
        errors = validate_subtasks(["Same part.", "Same part."], 3)
        assert len(errors) == 1
        assert "repeats an earlier part" in errors[0]

    def test_min_subtasks_constant(self):
        assert MIN_SUBTASKS == 2


class TestMakeSubtasks:
    def test_ids_and_titles_numbered(self):
        subtasks = make_subtasks(["First.", "Second."])
        assert [subtask.id for subtask in subtasks] == ["B1", "B2"]
        assert [subtask.title for subtask in subtasks] == ["Part 1", "Part 2"]
        assert [subtask.prompt for subtask in subtasks] == ["First.", "Second."]


class TestMergeBurst:
    def test_completed_parts_under_their_headings(self):
        merged = merge_burst(
            "Write the guide", [_completed(1, "Intro done."), _completed(2, "Body done.")]
        )
        assert merged.startswith("# Burst: Write the guide\n")
        assert "## B1 — Part 1\n\nIntro done." in merged
        assert "## B2 — Part 2\n\nBody done." in merged
        assert merged.rstrip().endswith("Completed 2 of 2 parts.")

    def test_failed_part_named_not_dropped(self):
        merged = merge_burst("Write the guide", [_completed(1), _failed(2, "TimeoutError")])
        assert "## B2 — Part 2 — FAILED" in merged
        assert "Not completed: TimeoutError." in merged
        assert "Completed 1 of 2 parts." in merged
        assert "Failed: B2 - retry them, do them directly, or narrow the task." in merged

    def test_failed_part_without_reason(self):
        merged = merge_burst(
            "Write the guide",
            [BurstSubtaskResult(id="B1", title="Part 1", status="failed")],
        )
        assert "Not completed: no reason given." in merged

    def test_empty_burst_merges_to_zero(self):
        merged = merge_burst("Write the guide", [])
        assert "Completed 0 of 0 parts." in merged


class TestBurstOutcome:
    def test_completed_and_failed_partitions(self):
        outcome = BurstOutcome(burst_no=1, task="T", results=[_completed(1), _failed(2)])
        assert [result.id for result in outcome.completed] == ["B1"]
        assert [result.id for result in outcome.failed] == ["B2"]
        assert outcome.all_completed() is False

    def test_all_completed(self):
        outcome = BurstOutcome(burst_no=1, task="T", results=[_completed(1), _completed(2)])
        assert outcome.all_completed() is True

    def test_empty_burst_completes_nothing(self):
        assert BurstOutcome(burst_no=1, task="T", results=[]).all_completed() is False

    def test_record_round_trip(self):
        outcome = BurstOutcome(
            burst_no=2,
            task="Write the guide",
            results=[_completed(1, "Intro."), _failed(2, "TimeoutError")],
            merged="# Burst: Write the guide\n",
        )
        restored = BurstOutcome.from_record(outcome.to_record())
        assert restored == outcome

    def test_record_round_trip_defaults(self):
        restored = BurstOutcome.from_record({})
        assert restored.burst_no == 0
        assert restored.task == ""
        assert restored.results == []
        assert restored.merged == ""

    def test_subtask_record_round_trip_defaults(self):
        restored = BurstSubtaskResult.from_record({})
        assert restored.id == ""
        assert restored.status == "failed"
        assert restored.result == ""
        assert restored.reason is None


class TestRenderBurstSummary:
    def test_summary_names_failed_parts(self):
        outcome = BurstOutcome(
            burst_no=1, task="Write the guide", results=[_completed(1), _failed(2, "TimeoutError")]
        )
        summary = render_burst_summary(outcome)
        assert summary.startswith("## Burst\n\nTask: Write the guide\n")
        assert "Parts: 2 - 1 completed, 1 failed." in summary
        assert "| B1 | Part 1 | completed |" in summary
        assert "| B2 | Part 2 | failed (TimeoutError) |" in summary

    def test_summary_failed_without_reason(self):
        outcome = BurstOutcome(
            burst_no=1,
            task="T",
            results=[BurstSubtaskResult(id="B1", title="Part 1", status="failed")],
        )
        assert "failed (no reason given)" in render_burst_summary(outcome)


class TestRunBurst:
    async def test_all_parts_complete_in_parallel(self):
        seen: list[str] = []

        async def run_fn(subtask: BurstSubtask) -> BurstSubtaskAnswer:
            seen.append(subtask.id)
            return BurstSubtaskAnswer(result=f"Result for {subtask.id}.")

        outcome = await run_burst([_subtask(1), _subtask(2)], "Do both", 1, run_fn)
        assert outcome.burst_no == 1
        assert outcome.task == "Do both"
        assert [result.status for result in outcome.results] == ["completed", "completed"]
        assert sorted(seen) == ["B1", "B2"]
        assert "Result for B1." in outcome.merged
        assert outcome.all_completed() is True

    async def test_raising_worker_records_failed(self):
        async def run_fn(subtask: BurstSubtask) -> BurstSubtaskAnswer:
            if subtask.id == "B2":
                raise TimeoutError("worker timed out")
            return BurstSubtaskAnswer(result="Fine.")

        outcome = await run_burst([_subtask(1), _subtask(2)], "Do both", 1, run_fn)
        assert [result.status for result in outcome.results] == ["completed", "failed"]
        assert outcome.results[1].reason == "TimeoutError"
        assert outcome.results[1].result == ""
        assert "B2 — Part 2 — FAILED" in outcome.merged
        assert outcome.all_completed() is False

    async def test_none_answer_records_failed(self):
        async def run_fn(subtask: BurstSubtask) -> BurstSubtaskAnswer | None:
            return None

        outcome = await run_burst([_subtask(1)], "Do it", 1, run_fn)
        assert outcome.results[0].status == "failed"
        assert outcome.results[0].reason == "empty result"

    async def test_empty_answer_records_failed(self):
        async def run_fn(subtask: BurstSubtask) -> BurstSubtaskAnswer:
            return BurstSubtaskAnswer(result="   ")

        outcome = await run_burst([_subtask(1)], "Do it", 1, run_fn)
        assert outcome.results[0].status == "failed"
        assert outcome.results[0].reason == "empty result"

    async def test_empty_answer_string_records_failed(self):
        async def run_fn(subtask: BurstSubtask) -> BurstSubtaskAnswer:
            return BurstSubtaskAnswer(result="")

        outcome = await run_burst([_subtask(1)], "Do it", 1, run_fn)
        assert outcome.results[0].status == "failed"

    async def test_a_cancelled_worker_records_failed_not_dropped(self):
        async def run_fn(subtask: BurstSubtask) -> BurstSubtaskAnswer:
            raise asyncio.CancelledError("worker cancelled")

        outcome = await run_burst([_subtask(1)], "Do it", 1, run_fn)
        assert outcome.results[0].status == "failed"
        assert outcome.results[0].reason == "CancelledError"


class TestBurstConfig:
    def test_defaults_mirror_the_subagents_ceiling(self):
        config = BurstConfig.model_validate({})
        assert config.max_subtasks == 3
        assert config.max_bursts == 3

    def test_at_least_two_subtasks(self):
        with pytest.raises(ValidationError):
            BurstConfig.model_validate({"max_subtasks": 1})

    def test_at_most_ten_subtasks(self):
        with pytest.raises(ValidationError):
            BurstConfig.model_validate({"max_subtasks": 11})

    def test_bursts_are_one_to_five(self):
        with pytest.raises(ValidationError):
            BurstConfig.model_validate({"max_bursts": 0})
        with pytest.raises(ValidationError):
            BurstConfig.model_validate({"max_bursts": 6})


class TestManifest:
    def test_burst_runs_are_in_the_payload(self):
        recorder = RunRecorder()
        recorder.burst_runs.append(
            {
                "burst": 1,
                "task": "Write the guide",
                "merged": "# Burst: Write the guide\n",
                "results": [
                    {
                        "id": "B1",
                        "title": "Part 1",
                        "status": "completed",
                        "result": "Intro.",
                        "reason": None,
                    }
                ],
            }
        )
        assert as_payload(recorder)["burst_runs"] == recorder.burst_runs

    def test_carried_over_keeps_earlier_bursts_and_caps_them(self):
        earlier = {"burst": 1, "task": "T", "merged": "", "results": []}
        previous = {"burst_runs": [earlier] * (MAX_RECORDED_BURSTS + 2)}
        payload = {"burst_runs": [{"burst": 2, "task": "T", "merged": "", "results": []}]}
        merged = carried_over(previous, payload)
        assert len(merged["burst_runs"]) == MAX_RECORDED_BURSTS
        assert merged["burst_runs"][0] == earlier

    def test_carried_over_without_earlier_bursts_is_unchanged(self):
        payload = {"burst_runs": []}
        assert carried_over({}, payload) is payload


class TestBurstTool:
    def _tool(self, recorder, max_subtasks=3, max_bursts=3):
        toolset = build_burst_toolset(recorder, max_subtasks, max_bursts)
        return toolset.tools["run_burst"].function

    async def test_an_invalid_split_is_a_refusal_not_a_burst(self):
        recorder = RunRecorder()
        tool = self._tool(recorder)
        result = await tool(None, "Do it", ["Only one part."])
        assert "at least 2" in result
        assert recorder.burst_runs == []

    async def test_too_many_subtasks_is_a_refusal(self):
        recorder = RunRecorder()
        tool = self._tool(recorder, max_subtasks=2)
        result = await tool(None, "Do it", ["One.", "Two.", "Three."])
        assert "at most 2" in result
        assert recorder.burst_runs == []

    async def test_max_bursts_is_a_refusal(self):
        recorder = RunRecorder()
        recorder.burst_runs.append({"burst": 1, "task": "T", "merged": "", "results": []})
        tool = self._tool(recorder, max_bursts=1)
        result = await tool(None, "Do it", ["One.", "Two."])
        assert "No more bursts" in result
        assert len(recorder.burst_runs) == 1

    async def test_a_completed_burst_is_recorded_and_merged(self, monkeypatch):
        async def fake_ambient(ctx, **kwargs):
            return BurstSubtaskAnswer(result="Part done.")

        monkeypatch.setattr(
            "app.agents.capabilities.burst._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        tool = self._tool(recorder)
        result = json.loads(await tool(None, "Write the guide", ["Intro.", "Body."]))
        assert result["burst"] == 1
        assert result["all_completed"] is True
        assert result["completed"] == 2
        assert result["failed"] == []
        assert "## B1 — Part 1" in result["merged"]
        assert "## Burst" in result["summary"]
        assert len(recorder.burst_runs) == 1
        assert recorder.burst_runs[0]["burst"] == 1

    async def test_a_failed_part_is_reported_not_dropped(self, monkeypatch):
        async def fake_ambient(ctx, **kwargs):
            if "Body." in kwargs["user_prompt"]:
                raise TimeoutError("worker timed out")
            return BurstSubtaskAnswer(result="Intro done.")

        monkeypatch.setattr(
            "app.agents.capabilities.burst._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        tool = self._tool(recorder)
        result = json.loads(await tool(None, "Write the guide", ["Intro.", "Body."]))
        assert result["all_completed"] is False
        assert result["completed"] == 1
        assert result["failed"] == [{"id": "B2", "title": "Part 2", "reason": "TimeoutError"}]
        assert "B2 — Part 2 — FAILED" in result["merged"]
        assert recorder.burst_runs[0]["results"][1]["status"] == "failed"

    async def test_a_second_burst_numbers_from_the_manifest(self, monkeypatch):
        async def fake_ambient(ctx, **kwargs):
            return BurstSubtaskAnswer(result="Done.")

        monkeypatch.setattr(
            "app.agents.capabilities.burst._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        recorder.burst_runs.append({"burst": 1, "task": "T", "merged": "", "results": []})
        tool = self._tool(recorder)
        result = json.loads(await tool(None, "Write more", ["A.", "B."]))
        assert result["burst"] == 2

    async def test_a_burst_past_the_manifest_cap_still_returns_its_merge(self, monkeypatch):
        async def fake_ambient(ctx, **kwargs):
            return BurstSubtaskAnswer(result="Done.")

        monkeypatch.setattr(
            "app.agents.capabilities.burst._toolset.run_ambient_agent", fake_ambient
        )
        recorder = RunRecorder()
        recorder.burst_runs.extend(
            {"burst": i + 1, "task": "T", "merged": "", "results": []}
            for i in range(MAX_RECORDED_BURSTS)
        )
        tool = self._tool(recorder, max_bursts=MAX_RECORDED_BURSTS + 1)
        result = json.loads(await tool(None, "Write more", ["A.", "B."]))
        assert result["burst"] == MAX_RECORDED_BURSTS + 1
        assert result["all_completed"] is True
        assert len(recorder.burst_runs) == MAX_RECORDED_BURSTS

    async def test_the_toolset_is_built_once(self):
        burst = Burst()
        assert burst.get_toolset() is burst.get_toolset()

    async def test_builder_with_empty_resources_still_builds(self):
        built = build_capabilities(
            [CapabilityBinding(capability_id="burst", config={})], resources={}
        )
        assert len(built) == 1
        assert isinstance(built[0], Burst)
        toolset = built[0].get_toolset()
        assert isinstance(toolset, FunctionToolset)
        tools = await toolset.get_tools(probe_context(built[0]))
        assert "run_burst" in tools
        assert built[0].get_instructions().startswith("Burst mode splits")
