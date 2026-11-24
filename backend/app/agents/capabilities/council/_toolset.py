"""The council's one tool: run a review round over the work."""

import json
from typing import Any

from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._ambient import run_ambient_agent
from app.agents.council import (
    CouncilReview,
    CouncilRound,
    ResolvedCouncilMember,
    render_council_table,
    round_satisfied,
    run_council_round,
)
from app.agents.manifest import MAX_RECORDED_COUNCIL_ROUNDS, RunRecorder

# Read-only, and scored: the delegate judges the work as it stands, it does
# not change it, and a score is what makes rounds comparable. `10` only when
# nothing needs to change, so a round that comes back satisfied means it.
_REVIEW_INSTRUCTIONS = (
    "You are a council delegate reviewing work for quality. Read the work and "
    "any context. Your review is read-only: judge the work as it stands, do not "
    "edit it and do not propose work outside its scope. Give a score out of 10 "
    "in the score field and a list of findings, each one short item saying what "
    "is wrong, missing, or risky. Score 10 only when nothing needs to change. "
    "If you cannot judge the work, leave the score empty rather than guessing."
)


def build_council_toolset(
    members: list[ResolvedCouncilMember],
    recorder: RunRecorder,
    threshold: int,
    max_rounds: int,
) -> FunctionToolset[Any]:
    """The council toolset: one tool, one round per call."""
    toolset: FunctionToolset[Any] = FunctionToolset()

    @toolset.tool
    async def run_council_review(ctx: RunContext[Any], work: str, context: str = "") -> str:
        """Run one council review round over the work.

        Use it when work is ready to be judged - before an audit, after fixing
        review comments, or when a second opinion from three providers would
        settle a disagreement. Each round fans the work out to the delegates in
        parallel, each on its own provider's model, and returns their scores
        out of 10 with their findings. One call is one round: after a round,
        fix what the delegates found and call it again for a fresh round, until
        every delegate scores at or above the agreement threshold.

        Args:
            work: The work to review - the implementation, draft, or proposal,
                as the delegates will read it.
            context: What the delegates need to judge it fairly: the request it
                answers, the constraints it had to meet, and what is
                deliberately out of scope. Empty when the work speaks for itself.

        Returns:
            A JSON string with the round number, whether every delegate is
            satisfied, the council table over all rounds so far, and each
            delegate's review with its score and findings. A delegate that gave
            no score reads `no_score`, and one that could not be reached reads
            `unavailable` with its reason - neither is ever given a score it
            did not give. When no more rounds are allowed, a refusal string
            instead, saying so.
        """
        if not members:
            return (
                "The council has no members configured, so there is nobody to "
                "review this. Add members in the council capability's settings "
                "before asking for a review."
            )
        round_no = len(recorder.council_rounds) + 1
        if round_no > max_rounds:
            return (
                f"No more council rounds: this agent allows at most {max_rounds} "
                f"rounds and {round_no - 1} have already run. Act on the last "
                "round's findings instead of asking for another review."
            )

        async def review_fn(
            member: ResolvedCouncilMember, work_text: str, context_text: str
        ) -> CouncilReview | None:
            prompt = f"Work to review:\n{work_text}"
            if context_text.strip():
                prompt += f"\n\nContext:\n{context_text}"
            return await run_ambient_agent(
                ctx,
                output_type=CouncilReview,
                user_prompt=prompt,
                instructions=_REVIEW_INSTRUCTIONS,
                model=member.model,
                model_settings=ModelSettings(thinking="high"),
            )

        round_ = await run_council_round(members, work, context, round_no, threshold, review_fn)
        if len(recorder.council_rounds) < MAX_RECORDED_COUNCIL_ROUNDS:
            recorder.council_rounds.append(round_.to_record(threshold))
        rounds = [CouncilRound.from_record(record) for record in recorder.council_rounds]
        # The round just run is part of the table even when the manifest is
        # already at its cap and could not record it.
        if all(record.round_no != round_.round_no for record in rounds):
            rounds.append(round_)
        return json.dumps(
            {
                "round": round_.round_no,
                "satisfied": round_satisfied(round_, threshold),
                "table": render_council_table(rounds),
                "reviews": [
                    {
                        "name": review.name,
                        "status": review.status,
                        "score": review.score,
                        "findings": list(review.findings),
                        "reason": review.reason,
                    }
                    for review in round_.reviews
                ],
            }
        )

    return toolset
