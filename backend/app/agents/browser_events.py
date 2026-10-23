"""What a surface hears while an agent is driving a browser.

A `browse_web` call is the longest-running tool this platform has and the one
whose progress matters most to watch. It is also the one where "the model chose
something" is a sentence worth reading: each step presses one of the elements the
page actually offers, and says what for. A transcript that records a tool call
and, forty seconds later, a paragraph, throws all of that away.

So the browse streams, and these are the frames. Three decisions shape them:

*The narration and the picture are separate frames.* A screenshot is two orders of
magnitude larger than the sentence describing the step, and encoding one should
never hold up the sentence. Split, a deployment that cannot afford frames turns
`preview` off and still gets the narration - and a client that has not drawn a
viewport yet still has something to show.

*Every frame carries its step number.* Frames arrive over the same socket as the
turn's text and a screenshot can land after the step that follows it. A surface
that assumed arrival order would draw the previous page under the current
caption, which is worse than drawing nothing.

*The finish frame is sent whatever the outcome.* `blocked` and `exhausted` are
outcomes, not errors - an engine that can say it could not proceed is the whole
point of this capability - and a failure still has to stop the spinner. A surface
left waiting for a frame that never comes is the defect this avoids.

The sink is `AgentDeps.browser_events`, set by surfaces that can show a run in
progress and `None` everywhere else - the same shape, and the same reasoning, as
`ask_user`, `request_approval`, `subagent_events` and `on_compaction`. A browse on
a surface that cannot narrate one still runs; it is simply not narrated.
"""

from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

BrowseOutcome = Literal["done", "blocked", "exhausted", "failed"]
"""How a browse ended, and all four are ordinary.

`done` reached the goal. `blocked` is the engine saying the page offers no action
that serves it - a login wall, a consent gate, a captcha - which is a legible
answer rather than a crash. `exhausted` hit the step ceiling. `failed` is the
browser or the endpoint, not the page.
"""


class BrowserEvent(BaseModel):
    """One thing that happened inside a browse, as a surface reads it.

    `kind` is the wire name as well as the discriminator, for the reason
    :class:`~app.agents.compaction_events.CompactionEvent` gives: a surface
    switches on the field it already parsed rather than on an envelope, so the
    two cannot drift into different spellings of one frame.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal[
        "browser_opened",
        "browser_step",
        "browser_frame",
        "browser_finished",
        "browser_held",
        "browser_released",
        "browser_needs_person",
        "browser_pointer",
    ]

    call_id: str = Field(
        description=(
            "Which `browse_web` call this belongs to. One turn can browse twice, "
            "and a surface that keyed on the run would draw the second browse's "
            "steps into the first one's panel."
        )
    )
    step: int = Field(
        ge=0,
        description=(
            "Which step of the loop this reports; 0 is the opening frame. Carried on "
            "every frame because a screenshot can arrive after the step that "
            "followed it, and a surface ordering by arrival would caption the wrong "
            "picture."
        ),
    )

    url: str | None = Field(
        default=None,
        description="Where the browser is. Present on the opening frame and on every step.",
    )
    title: str | None = Field(default=None, description="The page's title, when it has one.")

    max_steps: int | None = Field(
        default=None,
        description=(
            "The ceiling this browse runs under, on the opening frame only. A "
            "surface needs it to draw progress as 3/25 rather than as a number "
            "climbing towards nothing."
        ),
    )
    goal: str | None = Field(
        default=None,
        description="The task the model handed over, on the opening frame only.",
    )

    operation: str | None = Field(
        default=None,
        description=(
            "What this step did: CLICK, TYPE_TEXT, SELECT, SCROLL, NAVIGATE, BACK, "
            "WAIT, DONE or BLOCKED."
        ),
    )
    target: str | None = Field(
        default=None,
        description=(
            "The element the operation applies to, as the page labelled it - not an "
            "index. An index is meaningful only against a snapshot the surface "
            "never saw."
        ),
    )
    reason: str | None = Field(
        default=None,
        description=(
            "What the browsing model said this step is for, in its own sentence. "
            "Model-written text about a page, so a surface renders it as data."
        ),
    )
    run_id: str | None = Field(
        default=None,
        description=(
            "The run this browse belongs to, on the opening frame. With `call_id` "
            "it is the address of the browse's live view, `/browse/{run_id}/{call_id}`, "
            "which a person opens to watch or take over."
        ),
    )
    by: str | None = Field(
        default=None,
        description="Who took the browser over, by name, on `browser_held`.",
    )
    by_user_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Who took the browser over, by id, on `browser_held` - how a viewer "
            "tells that they are the one holding it. Names are not unique."
        ),
    )
    x: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "On `browser_pointer`: where the agent is about to click or type, as a "
            "fraction of the viewport's width, so a surface draws its cursor on the "
            "picture whatever size the picture is drawn at."
        ),
    )
    y: float | None = Field(
        default=None, ge=0, le=1, description="The same, as a fraction of its height."
    )
    image: str | None = Field(
        default=None,
        repr=False,
        description=(
            "A `data:` URL holding the viewport as JPEG, on `browser_frame` only. "
            "Bounded by the capability's `preview_width`, and absent entirely when "
            "`preview` is off."
        ),
    )

    outcome: BrowseOutcome | None = Field(
        default=None, description="How the browse ended, on the finish frame only."
    )
    detail: str | None = Field(
        default=None,
        description=(
            "One sentence about the outcome - what was blocking, or what broke; "
            "what the browser needs a person for, on `browser_needs_person`; the "
            "site whose sign-in was kept, on `browser_released`. Page-derived "
            "text, so a surface renders it as data and never as markup."
        ),
    )


BrowserEventSink = Callable[[BrowserEvent], Awaitable[bool]]
"""Where a surface hears what the browser is doing, or `None` where none can.

Awaited by the loop between steps, which is deliberate back-pressure: a socket
that cannot keep up slows the browse rather than growing an unbounded queue of
screenshots behind it.

**It answers whether the frame arrived**, unlike the delegation and compaction
sinks it is otherwise modelled on. Those carry sentences; this one carries
screenshots, and a run whose reader closed the tab deliberately carries on - so
without an answer the loop would go on capturing and base64-encoding a JPEG per
step for somebody who left. `False` is what lets it stop taking pictures while
the browse itself continues.
"""


BrowserKey = Literal[
    "Enter",
    "Tab",
    "Backspace",
    "Delete",
    "Escape",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "Home",
    "End",
    "PageUp",
    "PageDown",
]
"""The keys a person may press in a browser they took over, by their DOM names.

Printable text arrives as `type` and is inserted rather than pressed; these are the
keys with no character, and a closed list because each becomes a CDP key event
whose fields have to be right for the page to see the key at all.
"""


class BrowserCommand(BaseModel):
    """What a person watching a browse asks of it (#2128).

    `take_over` pauses the agent between steps and hands the tab to the person;
    the input commands act on it while they hold it, at the coordinates of the
    picture they see; `give_back` returns it and the agent carries on from the
    page as it is. `resize` makes the page as large as the window showing it, so
    the site lays itself out for that window instead of being a shrunk picture of
    a laptop screen. What a person types is never written to the transcript or the
    run's history - the history records only that somebody took over.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["take_over", "give_back", "click", "type", "key", "scroll", "resize"]
    x: float | None = Field(default=None, ge=0, le=4000)
    y: float | None = Field(default=None, ge=0, le=4000)
    text: str | None = Field(default=None, max_length=2000)
    key: BrowserKey | None = None
    dy: float | None = Field(default=None, ge=-5000, le=5000)
    width: int | None = Field(default=None, ge=320, le=1600, description="On `resize`, in CSS px.")
    height: int | None = Field(default=None, ge=320, le=2000, description="On `resize`, in CSS px.")
    scale: int | None = Field(
        default=None,
        ge=1,
        le=2,
        description="On `resize`: device pixels per CSS pixel, 2 for a high-density screen.",
    )
    remember: bool = Field(
        default=False,
        description=(
            "On `give_back`: keep the sign-in the person made while they held the "
            "browser, so later browses acting as them start signed in (#2129)."
        ),
    )
    by: str | None = Field(default=None, max_length=200)
    by_user_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Who sent it, stamped by the live view from the socket's session - "
            "never taken from the client. A sign-in is kept only for the person "
            "the run acts for, and this is how the browse tells."
        ),
    )


class BrowserControl(Protocol):
    """Where a browse hears from the people watching it, between and during steps."""

    async def poll(self) -> BrowserCommand | None:
        """The next command waiting, or `None` - without waiting for one."""

    async def wait(self, timeout: float) -> BrowserCommand | None:
        """The next command, waiting up to `timeout` seconds for one to arrive."""
