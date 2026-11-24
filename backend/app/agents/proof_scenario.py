"""Scenario-based end-to-end proof: observed evidence, not diffs.

Theo's tstack `full-send` skill ends every change the same way: reproduce the
original failure, apply the fix, then watch the same reproduction pass, and
record the evidence observed in the session - command output, a reproduction, a
screenshot. "Green mocked tests do not prove that the user experience works."
"When you cannot find a way to prove a change, you do not have full confidence.
Ask the user." Its merge gate requires proof covering every change in the diff,
required checks green, review bots finished with each finding fixed or dismissed
with a written reason, no human review still requesting changes, and a branch
up to date and mergeable - and never a `--admin` or other bypass.

This module is that gate's proof half, as pure functions over the run manifest.
A **proof scenario** names one reproduction for a change - a command to run, a
reproduction to watch, a UI flow to look at - and which files of the diff it
exercises. A **proof attempt** is one observed run of that scenario, before the
fix or after it, with what was actually seen. A scenario is proven only when
the same reproduction failed before the fix and passed after it, both times
with observed evidence. A unit-test run, green or otherwise, is recorded when
the agent hands one over but never counts as proof: it is the mocked green
`full-send` warns about.

Nothing here merges, approves, comments, or bypasses anything. The verdicts
are a report the agent reads before it asks a human to merge - and a change
with no observed proof says so, instead of reading as proven.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.agents.manifest import MAX_RECORDED_PROOF_SCENARIOS

#: The phases of one proof attempt, relative to the fix it proves.
ProofPhase = Literal["before_fix", "after_fix"]

#: What one proof attempt observed. Only the first four count as proof:
#: they are evidence seen in the session. `unit_test` is recorded when the
#: agent hands one over, and never counts - a green mocked test does not prove
#: the user experience works.
ProofEvidenceKind = Literal[
    "command_output",
    "reproduction",
    "screenshot",
    "ui_observation",
    "unit_test",
]

#: The evidence kinds that count as proof. Kept beside the literal so the
#: rule has one definition: observed evidence counts, a test run does not.
PROOF_EVIDENCE_KINDS: frozenset[str] = frozenset(
    {
        "command_output",
        "reproduction",
        "screenshot",
        "ui_observation",
    }
)

#: How a scenario is run: a command, a reproduction of the original failure,
#: or a UI flow the agent watches.
ProofScenarioKind = Literal["command", "reproduction", "ui"]

#: The outcome of one observed attempt. `inconclusive` is an attempt that ran
#: but proved nothing - the command errored before reaching the behaviour, the
#: screenshot caught the wrong screen - and counts as neither a pass nor a fail.
ProofAttemptStatus = Literal["passed", "failed", "inconclusive"]

#: How much of one change the proof covers.
ProofVerdict = Literal["proven", "partial", "unproven", "no_scenarios"]


@dataclass(slots=True)
class ProofAttempt:
    """One observed run of a proof scenario, before the fix or after it.

    Attributes:
        scenario_id: The scenario this attempt ran, stable across attempts.
        phase: Whether the fix was in place when this ran.
        status: What was observed - passed, failed, or inconclusive.
        evidence_kind: What kind of evidence this is. Only the observed kinds
            count as proof; `unit_test` never does.
        command: What was run or watched, so the attempt can be repeated.
        observed: What was actually seen - command output, the reproduction's
            result, a screenshot's description - clipped, never a secret.
        duration_ms: How long the attempt took, or 0 when not measured.
        observed_at: When it ran, or `None` when not stamped.
    """

    scenario_id: str
    phase: ProofPhase
    status: ProofAttemptStatus
    evidence_kind: ProofEvidenceKind
    command: str = ""
    observed: str = ""
    duration_ms: int = 0
    observed_at: datetime | None = None


@dataclass(slots=True)
class ProofScenario:
    """One reproduction for a change, and every attempt made at it.

    Attributes:
        id: The scenario's stable id, e.g. `P1`.
        name: What it reproduces, in one line.
        kind: How it runs - a command, a reproduction, or a UI flow.
        command: What to run or watch, so the reproduction can be repeated.
        covers: The diff files this scenario exercises. A file is covered only
            when a proven scenario names it.
        attempts: Every attempt made at this scenario, oldest first.
    """

    id: str
    name: str
    kind: ProofScenarioKind
    command: str = ""
    covers: list[str] = field(default_factory=list)
    attempts: list[ProofAttempt] = field(default_factory=list)


@dataclass(slots=True)
class ProofCoverage:
    """Which changes in the diff have observed proof, and which do not.

    Attributes:
        verdict: `proven` when every changed file is covered by a proven
            scenario, `partial` when some are, `unproven` when none are,
            `no_scenarios` when no scenario was recorded at all.
        covered_files: Changed files a proven scenario covers.
        uncovered_files: Changed files no proven scenario covers.
        proven_scenarios: Ids of the scenarios proven - failed before the fix,
            passed after it, both with observed evidence.
        unproven_scenarios: Ids of the scenarios recorded but not proven.
        covered_by: Each covered file, and the proven scenarios covering it.
    """

    verdict: ProofVerdict
    covered_files: list[str] = field(default_factory=list)
    uncovered_files: list[str] = field(default_factory=list)
    proven_scenarios: list[str] = field(default_factory=list)
    unproven_scenarios: list[str] = field(default_factory=list)
    covered_by: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class ProofGateItem:
    """One item of the merge gate's proof half, and whether it holds.

    Attributes:
        name: `proof`, `checks`, or `findings`.
        holds: Whether the item holds.
        reason: Why it holds, or what is still missing, in one line.
    """

    name: str
    holds: bool
    reason: str


@dataclass(slots=True)
class ProofGateChecklist:
    """The merge gate's proof half, as a report - never a merge decision.

    Attributes:
        items: The proof, checks, and findings items, in that order.
        ready: Whether every item holds. A change is ready only when its proof
            covers the diff, its required checks are green, and no review
            finding is still open. Ready here still merges nothing: merging
            needs the user's explicit request.
    """

    items: list[ProofGateItem] = field(default_factory=list)
    ready: bool = False


#: How many attempts one scenario keeps. A scenario retried more than six
#: times is being debugged, not proven - the oldest attempts go.
MAX_PROOF_ATTEMPTS_PER_SCENARIO = 6

#: How much of one attempt's observed output is kept. Command output is the
#: evidence, and unbounded output is how a manifest outgrows its ceiling.
_OBSERVED_CLIP = 4000


def evidence_counts_as_proof(kind: str) -> bool:
    """Whether evidence of this kind counts as proof.

    Observed evidence counts. A unit-test run does not - green mocked tests
    do not prove the user experience works - and neither does a kind nobody
    has named, which is refused rather than assumed to count.
    """
    return kind in PROOF_EVIDENCE_KINDS


def _normalize_reproduction(command: str) -> str:
    """Collapse whitespace so equivalent command strings identify one reproduction."""
    return " ".join(command.split())


def scenario_proven(scenario: ProofScenario) -> bool:
    """Whether this scenario proves its change.

    Proven means the same reproduction failed before the fix and passed after
    it, both times with evidence that counts as proof. Commands are compared
    after whitespace normalization. Two blank commands also match, which
    preserves command-less scenarios identified by a UI flow's name or id.
    One half alone proves nothing: a failure with no passing re-run is a bug
    report, and a pass with no failing before-run never showed the fix fixing
    anything. An inconclusive attempt and a unit-test attempt count as neither
    half.
    """
    before_failed = [
        attempt
        for attempt in scenario.attempts
        if attempt.phase == "before_fix"
        and attempt.status == "failed"
        and evidence_counts_as_proof(attempt.evidence_kind)
    ]
    after_passed = [
        attempt
        for attempt in scenario.attempts
        if attempt.phase == "after_fix"
        and attempt.status == "passed"
        and evidence_counts_as_proof(attempt.evidence_kind)
    ]
    return any(
        _normalize_reproduction(before.command) == _normalize_reproduction(after.command)
        for before in before_failed
        for after in after_passed
    )


def record_attempt(
    scenarios: list[ProofScenario],
    scenario: ProofScenario,
    attempt: ProofAttempt,
) -> list[ProofScenario]:
    """Record one attempt against its scenario, creating the scenario if needed.

    The scenario is matched by id: a later call with the same id updates the
    scenario's name, kind, command, and covered files rather than duplicating
    it. The attempt's observed output is clipped before it is kept, and the
    caps are enforced - the oldest attempts go first, then the oldest
    scenarios - so a run's proof list stays within its size ceiling.
    """
    existing = next((item for item in scenarios if item.id == scenario.id), None)
    if existing is None:
        existing = ProofScenario(
            id=scenario.id,
            name=scenario.name,
            kind=scenario.kind,
            command=scenario.command,
            covers=list(scenario.covers),
        )
        scenarios = [*scenarios, existing]
    else:
        existing.name = scenario.name
        existing.kind = scenario.kind
        existing.command = scenario.command
        existing.covers = list(scenario.covers)
    kept = ProofAttempt(
        scenario_id=scenario.id,
        phase=attempt.phase,
        status=attempt.status,
        evidence_kind=attempt.evidence_kind,
        command=attempt.command if attempt.command.strip() else scenario.command,
        observed=_clipped(attempt.observed),
        duration_ms=attempt.duration_ms,
        observed_at=attempt.observed_at or datetime.now(UTC),
    )
    existing.attempts = [*existing.attempts, kept][-MAX_PROOF_ATTEMPTS_PER_SCENARIO:]
    return scenarios[-MAX_RECORDED_PROOF_SCENARIOS:]


def proof_coverage(changed_files: list[str], scenarios: list[ProofScenario]) -> ProofCoverage:
    """Which changed files have observed proof, and which do not.

    A file is covered only by a proven scenario that names it - a scenario
    still unproven covers nothing, however many attempts it has. The verdict
    is `no_scenarios` when nothing was recorded, `proven` when every changed
    file is covered, `partial` when some are, and `unproven` when none are.
    An empty diff is vacuously proven: there is no change to prove.
    """
    if not scenarios:
        return ProofCoverage(
            verdict="no_scenarios",
            uncovered_files=list(changed_files),
        )
    proven = [scenario for scenario in scenarios if scenario_proven(scenario)]
    unproven = [scenario for scenario in scenarios if not scenario_proven(scenario)]
    covered_by: dict[str, list[str]] = {}
    for scenario in proven:
        for covered in scenario.covers:
            if covered in changed_files:
                covered_by.setdefault(covered, []).append(scenario.id)
    covered_files = [name for name in changed_files if name in covered_by]
    uncovered_files = [name for name in changed_files if name not in covered_by]
    if not uncovered_files:
        verdict: ProofVerdict = "proven"
    elif not covered_files:
        verdict = "unproven"
    else:
        verdict = "partial"
    return ProofCoverage(
        verdict=verdict,
        covered_files=covered_files,
        uncovered_files=uncovered_files,
        proven_scenarios=[scenario.id for scenario in proven],
        unproven_scenarios=[scenario.id for scenario in unproven],
        covered_by=covered_by,
    )


def merge_gate_proof(
    changed_files: list[str],
    scenarios: list[ProofScenario],
    *,
    checks_green: bool,
    checks_pending: int = 0,
    findings_open: int = 0,
) -> ProofGateChecklist:
    """The merge gate's proof half, as a checklist - a report, not a decision.

    Proof holds only when the coverage verdict is `proven`. Checks hold only
    when the required checks are green and none are still pending - a pending
    check is not a green one. Findings hold only when no review finding is
    still open. All three must hold for `ready`, and ready still merges
    nothing: the gate is checked by the agent, and merging needs the user's
    explicit request.
    """
    coverage = proof_coverage(changed_files, scenarios)
    if coverage.verdict == "proven":
        proof = ProofGateItem(
            name="proof", holds=True, reason="observed proof covers every changed file"
        )
    elif coverage.verdict == "no_scenarios":
        proof = ProofGateItem(
            name="proof",
            holds=False,
            reason="no proof scenario recorded - nothing observed proves this change",
        )
    else:
        proof = ProofGateItem(
            name="proof",
            holds=False,
            reason=(
                f"proof covers {len(coverage.covered_files)} of "
                f"{len(changed_files)} changed files; "
                f"unproven: {', '.join(coverage.uncovered_files)}"
            ),
        )
    if checks_green and checks_pending == 0:
        checks = ProofGateItem(name="checks", holds=True, reason="required checks green")
    elif checks_pending > 0:
        checks = ProofGateItem(
            name="checks",
            holds=False,
            reason=f"{checks_pending} required check(s) still pending",
        )
    else:
        checks = ProofGateItem(name="checks", holds=False, reason="required checks are not green")
    if findings_open == 0:
        findings = ProofGateItem(name="findings", holds=True, reason="no review finding still open")
    else:
        findings = ProofGateItem(
            name="findings",
            holds=False,
            reason=f"{findings_open} review finding(s) still open",
        )
    items = [proof, checks, findings]
    return ProofGateChecklist(items=items, ready=all(item.holds for item in items))


def describe_scenario(scenario: ProofScenario) -> str:
    """One line on a scenario: proven, or what its proof is still missing."""
    if scenario_proven(scenario):
        return f"{scenario.id} {scenario.name} - proven"
    before = any(
        attempt.phase == "before_fix"
        and attempt.status == "failed"
        and evidence_counts_as_proof(attempt.evidence_kind)
        for attempt in scenario.attempts
    )
    after = any(
        attempt.phase == "after_fix"
        and attempt.status == "passed"
        and evidence_counts_as_proof(attempt.evidence_kind)
        for attempt in scenario.attempts
    )
    if not before and not after:
        missing = "no failing before-fix attempt and no passing after-fix attempt"
    elif not before:
        missing = "no failing before-fix attempt"
    elif after:
        missing = "before and after ran different reproductions"
    else:
        missing = "no passing after-fix attempt"
    return f"{scenario.id} {scenario.name} - unproven ({missing})"


def render_proof_report(coverage: ProofCoverage, gate: ProofGateChecklist | None = None) -> str:
    """The coverage verdict as short text, for the run drawer and the agent.

    Names what is proven and what is not, file by file, so an unproven change
    reads as unproven rather than as a green diff. A change with no scenarios
    says so outright, and asks for a reproduction before it claims anything.
    """
    lines = [f"Proof: {coverage.verdict}"]
    for scenario_id in coverage.proven_scenarios:
        lines.append(f"  proven: {scenario_id}")
    for scenario_id in coverage.unproven_scenarios:
        lines.append(f"  unproven: {scenario_id}")
    for name in coverage.uncovered_files:
        lines.append(f"  no proof: {name}")
    if coverage.verdict == "no_scenarios":
        lines.append("  Record a reproduction scenario before claiming this change works.")
    if gate is not None:
        lines.append(f"Merge gate: {'ready' if gate.ready else 'not ready'}")
        for item in gate.items:
            mark = "ok" if item.holds else "missing"
            lines.append(f"  {mark}: {item.name} - {item.reason}")
    return "\n".join(lines)


def proof_scenario_to_dict(scenario: ProofScenario) -> dict[str, Any]:
    """A scenario as the manifest stores it: plain JSON values."""
    return {
        "id": scenario.id,
        "name": scenario.name,
        "kind": scenario.kind,
        "command": scenario.command,
        "covers": list(scenario.covers),
        "attempts": [
            {
                "scenario_id": attempt.scenario_id,
                "phase": attempt.phase,
                "status": attempt.status,
                "evidence_kind": attempt.evidence_kind,
                "command": attempt.command,
                "observed": attempt.observed,
                "duration_ms": attempt.duration_ms,
                "observed_at": attempt.observed_at.isoformat() if attempt.observed_at else None,
            }
            for attempt in scenario.attempts
        ],
    }


def proof_scenario_from_dict(data: dict[str, Any]) -> ProofScenario:
    """A stored scenario back again. Unknown fields are ignored: a row written
    by an older build carries whatever that build knew how to record."""
    attempts = []
    for item in data.get("attempts") or []:
        observed_at = item.get("observed_at")
        attempts.append(
            ProofAttempt(
                scenario_id=item.get("scenario_id", data.get("id", "")),
                phase=item.get("phase", "after_fix"),
                status=item.get("status", "inconclusive"),
                evidence_kind=item.get("evidence_kind", "command_output"),
                command=item.get("command", ""),
                observed=item.get("observed", ""),
                duration_ms=item.get("duration_ms", 0),
                observed_at=datetime.fromisoformat(observed_at) if observed_at else None,
            )
        )
    return ProofScenario(
        id=data.get("id", ""),
        name=data.get("name", ""),
        kind=data.get("kind", "command"),
        command=data.get("command", ""),
        covers=list(data.get("covers") or []),
        attempts=attempts,
    )


def _clipped(text: str, limit: int = _OBSERVED_CLIP) -> str:
    """`text` cut to `limit` characters, saying that it was."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… [truncated]"
