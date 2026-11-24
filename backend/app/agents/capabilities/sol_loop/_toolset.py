"""The sol-loop's one tool: run a review round over the work."""

import json
from typing import Any

from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._ambient import run_ambient_agent
from app.agents.manifest import MAX_RECORDED_SOL_LOOP_ROUNDS, RunRecorder
from app.agents.sol_loop import (
    ResolvedSolLoopReviewer,
    SolLoopReview,
    SolLoopRound,
    render_sol_loop_ledger,
    round_scope,
    run_sol_loop_round,
)

# Read-only, and bounded: the reviewer judges the work as it stands, it does
# not change it, and one call is one round. `APPROVE` only when nothing needs
# to change, so a round that comes back satisfied means it.
_REVIEW_INSTRUCTIONS = (
    "You are the sol-loop reviewer, reviewing work for quality. Read the work "
    "and any context. Your review is read-only: judge the work as it stands, do "
    "not edit it, do not commit or comment on anything, and do not start "
    "subagents or reviewers. Reply with a verdict line, VERDICT: APPROVE or "
    "VERDICT: CHANGES, then one line per finding in the form "
    "`S<n> [blocker|should|nit] file:line claim. Fix: suggestion`, with stable "
    "ids - a finding you raise again keeps the id it had. blocker is an "
    "intended case wrong, should is a real bug callers will hit, nit is the "
    "rest. Give APPROVE only when nothing needs to change. If you cannot judge "
    "the work, leave the verdict out rather than guessing."
)


def build_sol_loop_toolset(
    reviewer: ResolvedSolLoopReviewer | None,
    recorder: RunRecorder,
    max_rounds: int,
) -> FunctionToolset[Any]:
    """The sol-loop toolset: one tool, one round per call."""
    toolset: FunctionToolset[Any] = FunctionToolset()

    @toolset.tool
    async def run_sol_loop_review(
        ctx: RunContext[Any],
        work: str,
        context: str = "",
        scope: str = "",
        changed_files: list[str] | None = None,
        dispositions: dict[str, str] | None = None,
    ) -> str:
        """Run one sol-loop review round over the work.

        Use it when work is ready to be judged - after fixing review comments,
        or before filing a pull request. Each round asks the one configured
        reviewer for a verdict and findings with stable ids. One call is one
        round: after a round, fix what the reviewer found and call it again for
        a fresh round, until the verdict is APPROVE on the current diff. Round 1
        reviews the whole change; later rounds check only the changed code and
        the open findings, so pass the changed files and your dispositions for
        the last round's findings with each later call.

        Args:
            work: The work to review - the implementation, draft, or proposal,
                as the reviewer will read it. Round 1 is the whole change;
                later rounds are the changed code since the last round.
            context: What the reviewer needs to judge it fairly: the request it
                answers, the constraints it had to meet, and what is
                deliberately out of scope. Empty when the work speaks for itself.
            scope: Which scope this round reviews - `full` for round 1,
                `changed-only` after. Empty takes the round's own scope. The
                tool records what was passed; it cannot check it against git,
                so scoping the diff is the caller's job, per the sol-loop skill.
            changed_files: The files that changed since the last round, for a
                later round. The reviewer is told to check only these and the
                open findings.
            dispositions: What was done with the last round's findings, by
                finding id: `agree-fixed`, `disagree-with-evidence`, or
                `decline-nit`. Only these three are recorded; anything else is
                dropped rather than invented.

        Returns:
            A JSON string with the round number, its scope, the verdict,
            whether the loop is satisfied, why it stopped if it did, and each
            finding with its stable id, severity and fix suggestion, plus the
            findings ledger over all rounds so far. A reviewer that could not
            be reached reads `unavailable` with its reason - never a verdict
            it did not give, and never approval. When no more rounds are
            allowed, a refusal string instead, saying so.
        """
        if reviewer is None:
            return (
                "Sol-loop has no reviewer configured, so there is nobody to "
                "review this. Add a reviewer in the sol-loop capability's "
                "settings before asking for a review."
            )
        round_no = len(recorder.sol_loop_rounds) + 1
        if round_no > max_rounds:
            return (
                f"No more sol-loop rounds: this agent allows at most {max_rounds} "
                f"rounds and {round_no - 1} have already run. Act on the last "
                "round's findings instead of asking for another review."
            )
        effective_scope = scope or round_scope(round_no)

        async def review_fn(work_text: str, context_text: str) -> SolLoopReview | None:
            prompt = f"Work to review:\n{work_text}"
            if context_text.strip():
                prompt += f"\n\nContext:\n{context_text}"
            if changed_files:
                prompt += "\n\nChanged files since the last round:\n" + "\n".join(changed_files)
            if dispositions:
                lines = [f"{finding_id}: {outcome}" for finding_id, outcome in dispositions.items()]
                prompt += "\n\nDispositions for the last round's findings:\n" + "\n".join(lines)
            return await run_ambient_agent(
                ctx,
                output_type=SolLoopReview,
                user_prompt=prompt,
                instructions=_REVIEW_INSTRUCTIONS,
                model=reviewer.model,
                model_settings=ModelSettings(thinking="high"),
            )

        round_ = await run_sol_loop_round(
            reviewer,
            work,
            context,
            round_no,
            max_rounds,
            effective_scope,
            dispositions or {},
            review_fn,
        )
        record = round_.to_record()
        if changed_files:
            record["changed_files"] = list(changed_files)
        if len(recorder.sol_loop_rounds) < MAX_RECORDED_SOL_LOOP_ROUNDS:
            recorder.sol_loop_rounds.append(record)
        rounds = [SolLoopRound.from_record(item) for item in recorder.sol_loop_rounds]
        # The round just run is part of the ledger even when the manifest is
        # already at its cap and could not record it.
        if all(item.round_no != round_.round_no for item in rounds):
            rounds.append(round_)
        return json.dumps(
            {
                "round": round_.round_no,
                "scope": round_.scope,
                "verdict": round_.verdict,
                "satisfied": round_.satisfied(),
                "stop_reason": round_.stop_reason,
                "model": round_.model,
                "reason": round_.reason,
                "findings": [
                    {
                        "id": finding.id,
                        "severity": finding.severity,
                        "file": finding.file,
                        "line": finding.line,
                        "claim": finding.claim,
                        "fix": finding.fix,
                    }
                    for finding in round_.findings
                ],
                "ledger": render_sol_loop_ledger(rounds),
            }
        )

    return toolset
