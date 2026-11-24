"""The two tools of proof-scenario: record an attempt, ask for the verdict."""

import json
from typing import Any

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.manifest import MAX_RECORDED_PROOF_SCENARIOS, RunRecorder
from app.agents.proof_scenario import (
    ProofAttempt,
    ProofAttemptStatus,
    ProofEvidenceKind,
    ProofPhase,
    ProofScenario,
    ProofScenarioKind,
    describe_scenario,
    merge_gate_proof,
    proof_coverage,
    proof_scenario_from_dict,
    proof_scenario_to_dict,
    record_attempt,
    render_proof_report,
    scenario_proven,
)

_KINDS: frozenset[ProofScenarioKind] = frozenset({"command", "reproduction", "ui"})
_PHASES: frozenset[ProofPhase] = frozenset({"before_fix", "after_fix"})
_STATUSES: frozenset[ProofAttemptStatus] = frozenset({"passed", "failed", "inconclusive"})
_EVIDENCE_KINDS: frozenset[ProofEvidenceKind] = frozenset(
    {"command_output", "reproduction", "screenshot", "ui_observation", "unit_test"}
)


def build_proof_scenario_toolset(recorder: RunRecorder) -> FunctionToolset[Any]:
    """The proof-scenario toolset, bound to this run's recorder."""
    toolset: FunctionToolset[Any] = FunctionToolset()

    @toolset.tool
    async def proof_scenario_record(
        ctx: RunContext[Any],
        scenario_id: str,
        name: str,
        kind: str,
        command: str,
        covers: list[str],
        phase: str,
        status: str,
        evidence_kind: str,
        observed: str = "",
        duration_ms: int = 0,
    ) -> str:
        """Record one observed attempt at a proof scenario.

        Use it when a reproduction has actually been run: before the fix, to
        show the failure, and after it, to show the same reproduction
        passing. The attempt is stored on the run manifest with what was
        observed, so the proof for a change is read from the run rather
        than remembered. It never runs anything itself - the agent runs the
        reproduction and hands over what it saw.

        Args:
            scenario_id: The scenario's stable id, e.g. `P1`. A later call
                with the same id adds an attempt to the same scenario.
            name: What the scenario reproduces, in one line.
            kind: How it runs - `command`, `reproduction`, or `ui`.
            command: What to run or watch, so the reproduction can be
                repeated.
            covers: The diff files this scenario exercises.
            phase: `before_fix` or `after_fix`.
            status: What was observed - `passed`, `failed`, or
                `inconclusive` when the attempt ran but proved nothing.
            evidence_kind: What kind of evidence this is -
                `command_output`, `reproduction`, `screenshot`, or
                `ui_observation`. `unit_test` is recorded but never
                counts as proof.
            observed: What was actually seen - command output, the
                reproduction's result, a screenshot's description.
            duration_ms: How long the attempt took, or 0 when not measured.

        Returns:
            A JSON string with the scenario as recorded, whether it is
            proven yet, and one line describing what its proof is still
            missing. A refusal string instead when the id, name, kind,
            phase, status, or evidence kind is missing or unknown.
        """
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            return "Proof needs a scenario id, e.g. `P1`."
        if not isinstance(name, str) or not name.strip():
            return "Proof needs a scenario name, in one line."
        if kind not in _KINDS:
            return "Proof needs a scenario kind: `command`, `reproduction`, or `ui`."
        if phase not in _PHASES:
            return "Proof needs a phase: `before_fix` or `after_fix`."
        if status not in _STATUSES:
            return "Proof needs a status: `passed`, `failed`, or `inconclusive`."
        if evidence_kind not in _EVIDENCE_KINDS:
            return (
                "Proof needs an evidence kind: `command_output`, `reproduction`, "
                "`screenshot`, `ui_observation`, or `unit_test`."
            )
        if not isinstance(covers, list) or any(not isinstance(item, str) for item in covers):
            return "Proof needs `covers` as a list of file paths."
        scenarios = [proof_scenario_from_dict(item) for item in recorder.proof_scenarios]
        recorded = record_attempt(
            scenarios,
            ProofScenario(
                id=scenario_id.strip(),
                name=name.strip(),
                kind=kind,
                command=command,
                covers=list(covers),
            ),
            ProofAttempt(
                scenario_id=scenario_id.strip(),
                phase=phase,
                status=status,
                evidence_kind=evidence_kind,
                command=command,
                observed=observed,
                duration_ms=duration_ms,
            ),
        )
        recorder.proof_scenarios = [
            proof_scenario_to_dict(item) for item in recorded[-MAX_RECORDED_PROOF_SCENARIOS:]
        ]
        scenario = next(item for item in recorded if item.id == scenario_id.strip())
        return json.dumps(
            {
                "scenario": proof_scenario_to_dict(scenario),
                "proven": scenario_proven(scenario),
                "description": describe_scenario(scenario),
            }
        )

    @toolset.tool
    async def proof_scenario_verdict(
        ctx: RunContext[Any],
        changed_files: list[str],
        checks_green: bool = False,
        checks_pending: int = 0,
        findings_open: int = 0,
    ) -> str:
        """Report which changed files have observed proof, and which do not.

        Use it before asking for a merge: pass the changed files of the
        diff and what the checks and review bots say. It reports the
        coverage verdict - proven only when every changed file is covered
        by a scenario that failed before the fix and passed after it with
        observed evidence - and whether the merge gate's proof half holds.
        A green unit test never counts as proof here. The verdict is a
        report, not a decision: it never merges or approves anything.

        Args:
            changed_files: The files the diff changed.
            checks_green: Whether the required checks are green on the
                current head.
            checks_pending: How many required checks are still pending.
            findings_open: How many review findings are still open.

        Returns:
            A JSON string with the coverage verdict, the covered and
            uncovered files, the proven and unproven scenarios, the gate
            checklist, whether the gate is ready, and the report text. A
            refusal string instead when `changed_files` is not a list of
            file paths, or when a count is negative.
        """
        if not isinstance(changed_files, list) or any(
            not isinstance(item, str) for item in changed_files
        ):
            return "Proof needs `changed_files` as a list of file paths."
        if checks_pending < 0 or findings_open < 0:
            return "Proof needs non-negative counts for pending checks and open findings."
        scenarios = [proof_scenario_from_dict(item) for item in recorder.proof_scenarios]
        coverage = proof_coverage(list(changed_files), scenarios)
        gate = merge_gate_proof(
            list(changed_files),
            scenarios,
            checks_green=checks_green,
            checks_pending=checks_pending,
            findings_open=findings_open,
        )
        return json.dumps(
            {
                "verdict": coverage.verdict,
                "covered_files": coverage.covered_files,
                "uncovered_files": coverage.uncovered_files,
                "proven_scenarios": coverage.proven_scenarios,
                "unproven_scenarios": coverage.unproven_scenarios,
                "covered_by": coverage.covered_by,
                "gate_ready": gate.ready,
                "gate": [
                    {"name": item.name, "holds": item.holds, "reason": item.reason}
                    for item in gate.items
                ],
                "report": render_proof_report(coverage, gate),
            }
        )

    return toolset
