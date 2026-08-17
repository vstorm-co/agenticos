"""What a surface hears while a run's history is being summarised.

Compaction happens between a turn's model requests, where nothing streams. The
zero-LLM strategies edit a list and return, so nobody notices them. Summarising
is a whole model request over a history that is by definition long - seconds, on
the turn a person is already waiting on - and until this existed the chat simply
stopped for the length of it with nothing said. Waiting is tolerable; waiting
with no idea whether anything is happening is what makes somebody reload the page
and lose the turn.

Two frames, and deliberately only two. A start, so a surface can say the agent is
tidying its own history rather than stalled; and a finish carrying what it came
to, because "summarised 62 messages into 9" is the one sentence that explains
both the pause and why the next answer knows less than the last one did.

The sink is `AgentDeps.on_compaction`, set by surfaces that can show a run in
progress and `None` everywhere else - the same shape, and the same reasoning, as
`ask_user`, `request_approval` and `subagent_events`. A summary on a surface that
cannot narrate one still happens; it is simply not narrated.

**And a third, for the configuration that cannot work.** When the fixed overhead
alone is past the trigger, no summary can get under it and the platform refuses to
buy one on every request for ever - so it does nothing, which on screen is
indistinguishable from a setting that is working. `compaction_impossible` is that
silence given a voice: it says what the overhead is and what window it was
measured against, which is the pair somebody needs to pick a number that works. It
is sent once per run rather than per request, because it describes a setting
rather than an event.

**The finish frame is sent whatever the outcome.** A summary that raised leaves a
spinner running for ever otherwise, and the run itself carries on - the strategy
either returns a compacted history or the request goes out uncompacted, and
neither is a reason for the surface to stay stuck.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CompactionEvent(BaseModel):
    """One thing that happened to a run's history, as a surface reads it.

    `kind` is the wire name as well as the discriminator: a surface switches on
    the field it already parsed rather than on an envelope, which is what keeps
    the two from drifting into different spellings of one frame.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["compaction_started", "compaction_finished", "compaction_impossible"]

    messages_before: int | None = Field(
        default=None,
        description=(
            "How many messages the history held. Present on both frames: a surface "
            "that only learns it at the end cannot say what is being worked on while "
            "the work is happening."
        ),
    )
    overhead_tokens: int | None = Field(
        default=None,
        description=(
            "On `compaction_impossible`: what every request carries before a single "
            "message - the instructions and every tool schema, which no strategy can "
            "compact away."
        ),
    )
    window_tokens: int | None = Field(
        default=None,
        description="On `compaction_impossible`: the window the trigger was measured against.",
    )
    messages_after: int | None = Field(
        default=None,
        description=(
            "How many it holds now. Null on the start frame, and null on a finish "
            "that came from a summary which raised - the history is then whatever it "
            "was, and inventing a number would report a compaction that did not "
            "happen."
        ),
    )
