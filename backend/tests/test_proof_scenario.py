"""Scenario-based end-to-end proof: observed evidence, not diffs (#8)."""

import json
from datetime import UTC, datetime

import pytest

from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.proof_scenario import ProofScenarioCapability
from app.agents.capabilities.proof_scenario._toolset import (
    build_proof_scenario_toolset,
)
from app.agents.manifest import (
    MAX_RECORDED_PROOF_SCENARIOS,
    RunRecorder,
    as_payload,
    carried_over,
)
from app.agents.proof_scenario import (
    MAX_PROOF_ATTEMPTS_PER_SCENARIO,
    ProofAttempt,
    ProofAttemptStatus,
    ProofCoverage,
    ProofEvidenceKind,
    ProofPhase,
    ProofScenario,
    describe_scenario,
    evidence_counts_as_proof,
    merge_gate_proof,
    proof_coverage,
    proof_scenario_from_dict,
    proof_scenario_to_dict,
    record_attempt,
    render_proof_report,
    scenario_proven,
)


def _scenario(
    scenario_id: str = "P1",
    covers: list[str] | None = None,
    attempts: list[ProofAttempt] | None = None,
) -> ProofScenario:
    return ProofScenario(
        id=scenario_id,
        name="reproduce the failure",
        kind="reproduction",
        command="pytest tests/test_widget.py::test_renders -q",
        covers=list(covers) if covers is not None else ["backend/app/widget.py"],
        attempts=list(attempts) if attempts is not None else [],
    )


def _attempt(
    phase: ProofPhase = "before_fix",
    status: ProofAttemptStatus = "failed",
    kind: ProofEvidenceKind = "reproduction",
    observed: str = "AssertionError: widget did not render",
) -> ProofAttempt:
    return ProofAttempt(
        scenario_id="P1",
        phase=phase,
        status=status,
        evidence_kind=kind,
        command="pytest tests/test_widget.py::test_renders -q",
        observed=observed,
        duration_ms=120,
        observed_at=datetime(2026, 11, 12, 6, 0, tzinfo=UTC),
    )


def _proven() -> ProofScenario:
    return _scenario(
        attempts=[
            _attempt("before_fix", "failed", "reproduction"),
            _attempt("after_fix", "passed", "reproduction", "1 passed"),
        ]
    )


class TestEvidenceKinds:
    def test_observed_evidence_counts(self):
        for kind in ("command_output", "reproduction", "screenshot", "ui_observation"):
            assert evidence_counts_as_proof(kind) is True

    def test_a_unit_test_run_never_counts_as_proof(self):
        assert evidence_counts_as_proof("unit_test") is False

    def test_an_unnamed_kind_is_refused_rather_than_assumed(self):
        assert evidence_counts_as_proof("vibes") is False


class TestScenarioProven:
    def test_failed_before_and_passed_after_proves_it(self):
        assert scenario_proven(_proven()) is True

    def test_failed_before_and_passed_after_on_different_commands_do_not_prove_it(self):
        scenario = _scenario(
            attempts=[
                _attempt("before_fix", "failed"),
                _attempt("after_fix", "passed", observed="1 passed"),
            ]
        )
        scenario.attempts[0].command = "pytest tests/test_widget.py -q"
        scenario.attempts[1].command = "pytest tests/test_other.py -q"

        assert scenario_proven(scenario) is False
        assert proof_coverage(["backend/app/widget.py"], [scenario]).verdict == "unproven"
        gate = merge_gate_proof(["backend/app/widget.py"], [scenario], checks_green=True)
        assert gate.ready is False

    def test_matching_commands_with_different_whitespace_prove_it(self):
        scenario = _proven()
        scenario.attempts[0].command = "  pytest   tests/test_widget.py -q  "
        scenario.attempts[1].command = "pytest tests/test_widget.py -q"

        assert scenario_proven(scenario) is True

    def test_both_blank_commands_prove_a_commandless_scenario(self):
        scenario = _scenario(
            attempts=[
                _attempt("before_fix", "failed"),
                _attempt("after_fix", "passed", observed="visible"),
            ]
        )
        scenario.command = ""
        scenario.attempts[0].command = ""
        scenario.attempts[1].command = ""

        assert scenario_proven(scenario) is True

    def test_a_pass_with_no_failing_before_run_proves_nothing(self):
        assert (
            scenario_proven(
                _scenario(attempts=[_attempt("after_fix", "passed", "reproduction", "1 passed")])
            )
            is False
        )

    def test_a_failure_with_no_passing_after_run_proves_nothing(self):
        assert scenario_proven(_scenario(attempts=[_attempt()])) is False

    def test_inconclusive_attempts_count_as_neither_half(self):
        scenario = _scenario(
            attempts=[
                _attempt("before_fix", "inconclusive", "reproduction", "command errored first"),
                _attempt("after_fix", "inconclusive", "reproduction", "wrong screen"),
            ]
        )
        assert scenario_proven(scenario) is False

    def test_a_unit_test_attempt_counts_as_neither_half(self):
        scenario = _scenario(
            attempts=[
                _attempt("before_fix", "failed", "unit_test"),
                _attempt("after_fix", "passed", "unit_test", "1 passed"),
            ]
        )
        assert scenario_proven(scenario) is False

    def test_a_unit_test_before_run_does_not_prove_the_fix(self):
        scenario = _scenario(
            attempts=[
                _attempt("before_fix", "failed", "unit_test"),
                _attempt("after_fix", "passed", "reproduction", "1 passed"),
            ]
        )
        assert scenario_proven(scenario) is False

    def test_a_unit_test_after_run_does_not_prove_the_fix(self):
        scenario = _scenario(
            attempts=[
                _attempt("before_fix", "failed", "reproduction"),
                _attempt("after_fix", "passed", "unit_test", "1 passed"),
            ]
        )
        assert scenario_proven(scenario) is False

    def test_no_attempts_proves_nothing(self):
        assert scenario_proven(_scenario()) is False


class TestRecordAttempt:
    def test_creates_the_scenario_on_first_attempt(self):
        recorded = record_attempt([], _scenario(), _attempt())
        assert len(recorded) == 1
        assert recorded[0].id == "P1"
        assert len(recorded[0].attempts) == 1
        assert recorded[0].attempts[0].status == "failed"

    def test_a_repeat_call_updates_the_scenario_instead_of_duplicating_it(self):
        recorded = record_attempt([], _scenario(), _attempt())
        updated = _scenario(covers=["backend/app/widget.py", "frontend/src/widget.tsx"])
        updated.name = "reproduce the failure, wider"
        recorded = record_attempt(
            recorded, updated, _attempt("after_fix", "passed", "reproduction", "1 passed")
        )
        assert len(recorded) == 1
        assert recorded[0].name == "reproduce the failure, wider"
        assert recorded[0].covers == ["backend/app/widget.py", "frontend/src/widget.tsx"]
        assert len(recorded[0].attempts) == 2

    def test_blank_attempt_commands_snapshot_the_scenario_command_when_recorded(self):
        first = _scenario()
        first.command = "pytest tests/test_widget.py -q"
        before = _attempt("before_fix", "failed")
        before.command = ""
        recorded = record_attempt([], first, before)

        later = _scenario()
        later.command = "pytest tests/test_other.py -q"
        after = _attempt("after_fix", "passed", observed="1 passed")
        after.command = ""
        recorded = record_attempt(recorded, later, after)

        assert [attempt.command for attempt in recorded[0].attempts] == [
            "pytest tests/test_widget.py -q",
            "pytest tests/test_other.py -q",
        ]
        assert scenario_proven(recorded[0]) is False

    def test_observed_output_is_clipped_before_it_is_kept(self):
        recorded = record_attempt([], _scenario(), _attempt(observed="x" * 5000))
        kept = recorded[0].attempts[0].observed
        assert kept.endswith("… [truncated]")
        assert len(kept) < 5000

    def test_a_missing_timestamp_is_stamped(self):
        attempt = _attempt()
        attempt.observed_at = None
        recorded = record_attempt([], _scenario(), attempt)
        assert recorded[0].attempts[0].observed_at is not None

    def test_attempts_are_capped_oldest_first(self):
        recorded: list[ProofScenario] = []
        for index in range(MAX_PROOF_ATTEMPTS_PER_SCENARIO + 1):
            recorded = record_attempt(recorded, _scenario(), _attempt(observed=f"attempt {index}"))
        assert len(recorded[0].attempts) == MAX_PROOF_ATTEMPTS_PER_SCENARIO
        assert recorded[0].attempts[0].observed == "attempt 1"
        assert recorded[0].attempts[-1].observed == f"attempt {MAX_PROOF_ATTEMPTS_PER_SCENARIO}"

    def test_scenarios_are_capped_oldest_first(self):
        recorded: list[ProofScenario] = []
        for index in range(MAX_RECORDED_PROOF_SCENARIOS + 1):
            scenario = _scenario(f"P{index}")
            recorded = record_attempt(recorded, scenario, _attempt())
        assert len(recorded) == MAX_RECORDED_PROOF_SCENARIOS
        assert recorded[0].id == "P1"
        assert recorded[-1].id == f"P{MAX_RECORDED_PROOF_SCENARIOS}"


class TestProofCoverage:
    def test_no_scenarios_means_no_proof(self):
        coverage = proof_coverage(["backend/app/widget.py"], [])
        assert coverage.verdict == "no_scenarios"
        assert coverage.uncovered_files == ["backend/app/widget.py"]
        assert coverage.covered_files == []

    def test_a_proven_scenario_covering_every_file_proves_the_diff(self):
        coverage = proof_coverage(["backend/app/widget.py"], [_proven()])
        assert coverage.verdict == "proven"
        assert coverage.covered_files == ["backend/app/widget.py"]
        assert coverage.uncovered_files == []
        assert coverage.proven_scenarios == ["P1"]
        assert coverage.covered_by == {"backend/app/widget.py": ["P1"]}

    def test_a_proven_scenario_covering_some_files_is_partial(self):
        coverage = proof_coverage(["backend/app/widget.py", "frontend/src/widget.tsx"], [_proven()])
        assert coverage.verdict == "partial"
        assert coverage.covered_files == ["backend/app/widget.py"]
        assert coverage.uncovered_files == ["frontend/src/widget.tsx"]

    def test_an_unproven_scenario_covers_nothing(self):
        coverage = proof_coverage(["backend/app/widget.py"], [_scenario(attempts=[_attempt()])])
        assert coverage.verdict == "unproven"
        assert coverage.covered_files == []
        assert coverage.unproven_scenarios == ["P1"]

    def test_a_proven_scenario_covering_an_unchanged_file_covers_nothing(self):
        scenario = _proven()
        scenario.covers = ["docs/notes.md"]
        coverage = proof_coverage(["backend/app/widget.py"], [scenario])
        assert coverage.verdict == "unproven"
        assert coverage.proven_scenarios == ["P1"]
        assert coverage.covered_files == []

    def test_an_empty_diff_is_vacuously_proven(self):
        coverage = proof_coverage([], [_proven()])
        assert coverage.verdict == "proven"
        assert coverage.covered_files == []
        assert coverage.uncovered_files == []

    def test_two_proven_scenarios_can_cover_a_file_together(self):
        second = _scenario(
            "P2",
            covers=["frontend/src/widget.tsx"],
            attempts=[
                _attempt("before_fix", "failed", "screenshot"),
                _attempt("after_fix", "passed", "screenshot", "widget renders"),
            ],
        )
        second.attempts[0].scenario_id = "P2"
        second.attempts[1].scenario_id = "P2"
        coverage = proof_coverage(
            ["backend/app/widget.py", "frontend/src/widget.tsx"], [_proven(), second]
        )
        assert coverage.verdict == "proven"
        assert coverage.covered_by == {
            "backend/app/widget.py": ["P1"],
            "frontend/src/widget.tsx": ["P2"],
        }


class TestMergeGateProof:
    def test_ready_when_proof_checks_and_findings_all_hold(self):
        gate = merge_gate_proof(["backend/app/widget.py"], [_proven()], checks_green=True)
        assert gate.ready is True
        assert [item.name for item in gate.items] == ["proof", "checks", "findings"]
        assert all(item.holds for item in gate.items)

    def test_not_ready_when_proof_is_partial(self):
        gate = merge_gate_proof(
            ["backend/app/widget.py", "frontend/src/widget.tsx"],
            [_proven()],
            checks_green=True,
        )
        assert gate.ready is False
        assert gate.items[0].holds is False
        assert "unproven: frontend/src/widget.tsx" in gate.items[0].reason

    def test_not_ready_when_no_scenario_was_recorded(self):
        gate = merge_gate_proof(["backend/app/widget.py"], [], checks_green=True)
        assert gate.ready is False
        assert "no proof scenario recorded" in gate.items[0].reason

    def test_not_ready_when_checks_are_still_pending(self):
        gate = merge_gate_proof(
            ["backend/app/widget.py"], [_proven()], checks_green=True, checks_pending=2
        )
        assert gate.ready is False
        assert gate.items[1].holds is False
        assert "2 required check(s) still pending" in gate.items[1].reason

    def test_not_ready_when_checks_are_not_green(self):
        gate = merge_gate_proof(["backend/app/widget.py"], [_proven()], checks_green=False)
        assert gate.ready is False
        assert "not green" in gate.items[1].reason

    def test_not_ready_when_a_finding_is_still_open(self):
        gate = merge_gate_proof(
            ["backend/app/widget.py"], [_proven()], checks_green=True, findings_open=1
        )
        assert gate.ready is False
        assert gate.items[2].holds is False
        assert "1 review finding(s) still open" in gate.items[2].reason


class TestDescribeAndRender:
    def test_a_proven_scenario_describes_itself_as_proven(self):
        assert describe_scenario(_proven()) == "P1 reproduce the failure - proven"

    def test_a_scenario_with_no_attempts_names_both_missing_halves(self):
        assert describe_scenario(_scenario()).endswith(
            "unproven (no failing before-fix attempt and no passing after-fix attempt)"
        )

    def test_a_scenario_with_only_a_failing_before_run_names_the_missing_half(self):
        assert describe_scenario(_scenario(attempts=[_attempt()])).endswith(
            "unproven (no passing after-fix attempt)"
        )

    def test_a_scenario_with_only_a_passing_after_run_names_the_missing_half(self):
        scenario = _scenario(attempts=[_attempt("after_fix", "passed", "reproduction", "1 passed")])
        assert describe_scenario(scenario).endswith("unproven (no failing before-fix attempt)")

    def test_different_commands_explain_why_a_scenario_is_unproven(self):
        scenario = _scenario(
            attempts=[
                _attempt("before_fix", "failed"),
                _attempt("after_fix", "passed", observed="1 passed"),
            ]
        )
        scenario.attempts[0].command = "pytest tests/test_widget.py -q"
        scenario.attempts[1].command = "pytest tests/test_other.py -q"

        assert "before and after ran different reproductions" in describe_scenario(scenario)

    def test_the_report_names_proven_and_unproven_files(self):
        coverage = proof_coverage(["backend/app/widget.py", "frontend/src/widget.tsx"], [_proven()])
        report = render_proof_report(coverage)
        assert report.startswith("Proof: partial")
        assert "proven: P1" in report
        assert "no proof: frontend/src/widget.tsx" in report

    def test_the_report_names_an_unproven_scenario(self):
        coverage = proof_coverage(["backend/app/widget.py"], [_scenario(attempts=[_attempt()])])
        report = render_proof_report(coverage)
        assert report.startswith("Proof: unproven")
        assert "unproven: P1" in report
        assert "no proof: backend/app/widget.py" in report

    def test_the_report_says_so_when_nothing_was_recorded(self):
        coverage = proof_coverage(["backend/app/widget.py"], [])
        report = render_proof_report(coverage)
        assert "Proof: no_scenarios" in report
        assert "Record a reproduction scenario" in report

    def test_the_report_carries_the_gate_when_given(self):
        coverage = proof_coverage(["backend/app/widget.py"], [_proven()])
        gate = merge_gate_proof(["backend/app/widget.py"], [_proven()], checks_green=True)
        report = render_proof_report(coverage, gate)
        assert "Merge gate: ready" in report
        assert "ok: proof - observed proof covers every changed file" in report

    def test_the_report_marks_a_gate_item_that_does_not_hold(self):
        coverage = proof_coverage(["backend/app/widget.py"], [])
        gate = merge_gate_proof(["backend/app/widget.py"], [], checks_green=True)
        report = render_proof_report(coverage, gate)
        assert "Merge gate: not ready" in report
        assert "missing: proof - no proof scenario recorded" in report


class TestDictRoundTrip:
    def test_a_scenario_survives_the_manifest_and_back(self):
        scenario = _proven()
        restored = proof_scenario_from_dict(proof_scenario_to_dict(scenario))
        assert restored == scenario
        assert (
            proof_scenario_to_dict(restored)["attempts"][0]["command"]
            == scenario.attempts[0].command
        )

    def test_from_dict_tolerates_a_row_from_an_older_build(self):
        restored = proof_scenario_from_dict({"id": "P9", "name": "old row"})
        assert restored.id == "P9"
        assert restored.name == "old row"
        assert restored.kind == "command"
        assert restored.covers == []
        assert restored.attempts == []

    def test_from_dict_tolerates_a_bare_attempt(self):
        restored = proof_scenario_from_dict({"id": "P9", "attempts": [{"status": "passed"}]})
        assert len(restored.attempts) == 1
        assert restored.attempts[0].scenario_id == "P9"
        assert restored.attempts[0].phase == "after_fix"
        assert restored.attempts[0].evidence_kind == "command_output"
        assert restored.attempts[0].observed_at is None

    def test_to_dict_writes_a_missing_timestamp_as_null(self):
        scenario = _scenario(attempts=[_attempt()])
        scenario.attempts[0].observed_at = None
        assert proof_scenario_to_dict(scenario)["attempts"][0]["observed_at"] is None

    def test_coverage_defaults_are_empty(self):
        assert ProofCoverage(verdict="proven").covered_files == []
        assert ProofCoverage(verdict="proven").covered_by == {}


pytestmark = pytest.mark.anyio


class TestProofScenarioTool:
    def _toolset(self, recorder=None):
        recorder = recorder if recorder is not None else RunRecorder()
        return build_proof_scenario_toolset(recorder), recorder

    def _record(self, toolset):
        return toolset.tools["proof_scenario_record"].function

    def _verdict(self, toolset):
        return toolset.tools["proof_scenario_verdict"].function

    async def test_a_before_and_after_pair_proves_the_scenario(self):
        toolset, recorder = self._toolset()
        record = self._record(toolset)
        before = json.loads(
            await record(
                None,
                "P1",
                "reproduce the failure",
                "reproduction",
                "pytest tests/test_widget.py -q",
                ["backend/app/widget.py"],
                "before_fix",
                "failed",
                "reproduction",
                "AssertionError",
            )
        )
        assert before["proven"] is False
        assert "no passing after-fix attempt" in before["description"]
        after = json.loads(
            await record(
                None,
                "P1",
                "reproduce the failure",
                "reproduction",
                "pytest tests/test_widget.py -q",
                ["backend/app/widget.py"],
                "after_fix",
                "passed",
                "reproduction",
                "1 passed",
            )
        )
        assert after["proven"] is True
        assert after["description"].endswith("proven")
        assert len(recorder.proof_scenarios) == 1
        assert len(recorder.proof_scenarios[0]["attempts"]) == 2

    async def test_a_unit_test_attempt_is_recorded_but_never_proves(self):
        toolset, _ = self._toolset()
        record = self._record(toolset)
        await record(
            None,
            "P1",
            "reproduce the failure",
            "reproduction",
            "pytest tests/test_widget.py -q",
            ["backend/app/widget.py"],
            "before_fix",
            "failed",
            "unit_test",
            "1 failed",
        )
        after = json.loads(
            await record(
                None,
                "P1",
                "reproduce the failure",
                "reproduction",
                "pytest tests/test_widget.py -q",
                ["backend/app/widget.py"],
                "after_fix",
                "passed",
                "unit_test",
                "1 passed",
            )
        )
        assert after["proven"] is False

    async def test_bad_arguments_are_refusals_not_records(self):
        toolset, recorder = self._toolset()
        record = self._record(toolset)
        assert "scenario id" in await record(
            None,
            " ",
            "name",
            "reproduction",
            "cmd",
            [],
            "before_fix",
            "failed",
            "reproduction",
        )
        assert "scenario name" in await record(
            None,
            "P1",
            " ",
            "reproduction",
            "cmd",
            [],
            "before_fix",
            "failed",
            "reproduction",
        )
        assert "scenario kind" in await record(
            None,
            "P1",
            "name",
            "vibes",
            "cmd",
            [],
            "before_fix",
            "failed",
            "reproduction",
        )
        assert "phase" in await record(
            None,
            "P1",
            "name",
            "reproduction",
            "cmd",
            [],
            "during",
            "failed",
            "reproduction",
        )
        assert "status" in await record(
            None,
            "P1",
            "name",
            "reproduction",
            "cmd",
            [],
            "before_fix",
            "maybe",
            "reproduction",
        )
        assert "evidence kind" in await record(
            None,
            "P1",
            "name",
            "reproduction",
            "cmd",
            [],
            "before_fix",
            "failed",
            "vibes",
        )
        assert "covers" in await record(
            None,
            "P1",
            "name",
            "reproduction",
            "cmd",
            "not-a-list",
            "before_fix",
            "failed",
            "reproduction",
        )
        assert recorder.proof_scenarios == []

    async def test_the_verdict_reports_coverage_and_the_gate(self):
        toolset, _ = self._toolset()
        record = self._record(toolset)
        await record(
            None,
            "P1",
            "reproduce the failure",
            "reproduction",
            "pytest tests/test_widget.py -q",
            ["backend/app/widget.py"],
            "before_fix",
            "failed",
            "reproduction",
            "AssertionError",
        )
        await record(
            None,
            "P1",
            "reproduce the failure",
            "reproduction",
            "pytest tests/test_widget.py -q",
            ["backend/app/widget.py"],
            "after_fix",
            "passed",
            "reproduction",
            "1 passed",
        )
        verdict = json.loads(
            await self._verdict(toolset)(None, ["backend/app/widget.py"], checks_green=True)
        )
        assert verdict["verdict"] == "proven"
        assert verdict["gate_ready"] is True
        assert "Proof: proven" in verdict["report"]
        assert "Merge gate: ready" in verdict["report"]

    async def test_the_verdict_names_unproven_files(self):
        toolset, _ = self._toolset()
        verdict = json.loads(
            await self._verdict(toolset)(None, ["backend/app/widget.py"], checks_green=True)
        )
        assert verdict["verdict"] == "no_scenarios"
        assert verdict["uncovered_files"] == ["backend/app/widget.py"]
        assert verdict["gate_ready"] is False

    async def test_the_verdict_refuses_bad_arguments(self):
        toolset, _ = self._toolset()
        verdict = self._verdict(toolset)
        assert "changed_files" in await verdict(None, "not-a-list")
        assert "non-negative" in await verdict(None, [], checks_pending=-1)
        assert "non-negative" in await verdict(None, [], findings_open=-1)

    async def test_the_manifest_keeps_twenty_scenarios(self):
        recorder = RunRecorder()
        recorder.proof_scenarios = [
            {"id": f"old-{n}", "name": "old", "kind": "command", "attempts": []}
            for n in range(MAX_RECORDED_PROOF_SCENARIOS)
        ]
        toolset, _ = self._toolset(recorder)
        await self._record(toolset)(
            None,
            "P-new",
            "new scenario",
            "command",
            "make check",
            ["backend/app/widget.py"],
            "after_fix",
            "passed",
            "command_output",
            "ok",
        )
        assert len(recorder.proof_scenarios) == MAX_RECORDED_PROOF_SCENARIOS
        assert recorder.proof_scenarios[0]["id"] == "old-1"
        assert recorder.proof_scenarios[-1]["id"] == "P-new"


class TestProofScenarioManifest:
    def test_the_payload_carries_the_scenarios(self):
        recorder = RunRecorder()
        recorder.proof_scenarios = [
            proof_scenario_to_dict(_proven()),
            proof_scenario_to_dict(_scenario("P2")),
        ]
        payload = as_payload(recorder)
        assert len(payload["proof_scenarios"]) == 2
        assert payload["proof_scenarios"][0]["id"] == "P1"

    def test_scenarios_carry_over_across_segments(self):
        previous = {"proof_scenarios": [proof_scenario_to_dict(_proven())]}
        payload = {"proof_scenarios": [proof_scenario_to_dict(_scenario("P2"))]}
        merged = carried_over(previous, payload)
        assert [item["id"] for item in merged["proof_scenarios"]] == ["P1", "P2"]

    def test_nothing_carries_over_when_nothing_was_recorded(self):
        payload = {"proof_scenarios": []}
        assert carried_over({}, payload) is payload


class TestProofScenarioBuilder:
    def test_builder_with_empty_resources_still_builds(self):
        built = build_capabilities(
            [CapabilityBinding(capability_id="proof_scenario", config={})],
            resources={},
        )
        assert len(built) == 1
        assert isinstance(built[0], ProofScenarioCapability)
        toolset = built[0].get_toolset()
        assert "proof_scenario_record" in toolset.tools
        assert "proof_scenario_verdict" in toolset.tools
        # The toolset is built once: a second call returns the same one.
        assert built[0].get_toolset() is toolset
        assert "Prove a change with observed evidence" in built[0].get_instructions()

    def test_builder_hands_the_capability_the_run_recorder(self):
        recorder = RunRecorder()
        built = build_capabilities(
            [CapabilityBinding(capability_id="proof_scenario", config={})],
            resources={"proof_scenario_recorder": recorder},
        )
        assert built[0].recorder is recorder
