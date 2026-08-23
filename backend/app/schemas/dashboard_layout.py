"""Schemas for a person's saved dashboard arrangement.

The write and read shapes are deliberately asymmetric, and the asymmetry is the
whole point:

- **On write**, every placement is validated against the widget registry
  (:data:`WIDGET_IDS`) and the closed span set (:data:`SPANS`). A typo — a
  widget id that never existed — is a 422 at the boundary, not a card that
  silently never renders.
- **On read**, a placement is returned as it was stored, unchecked. A widget id
  that was valid when it was saved may have been *retired* since, and the
  frontend registry drops what it no longer knows at render time. Re-validating
  here would turn one retired widget into a 500 that takes the whole saved
  layout down with it — the opposite of "render the rest of the page".

:data:`WIDGET_IDS`, :data:`SPANS` and :data:`ROWS` mirror
`frontend/src/lib/dashboard/registry.ts`. `tests/test_dashboard_registry.py`
fails if they drift, in either direction, so the mirror cannot rot the way a
hand-copied list does.

The same placement shape serves two rows: the caller's single *active*
arrangement (`dashboard_layouts`, one per person per organization) and their
saved *presets* (`dashboard_presets`, named arrangements they switch between).
A preset is applied by writing its entries as the active arrangement, so the
two are validated identically.

An entry is one of two kinds, discriminated on `kind`:

- a **widget** placement (`kind="widget"`, the implied default), carrying the
  widget id, its `span` and an optional `rows` height;
- a **section divider** (`kind="section"`), a full-width heading carrying a
  free-text `label`, an `accent` colour that tints the cards beneath it, and
  a `collapsed` flag folding the section down to its heading.

The discriminator is deliberately forgiving: an entry with no `kind` at all is
read as a widget, so an arrangement saved before dividers existed still
validates on the next write rather than 422-ing on a shape it predates.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, get_args
from uuid import UUID

from pydantic import Discriminator, Field, Tag, field_validator

from app.schemas.base import BaseSchema, TimestampSchema

# The closed set of card widths the 12-column grid supports. Narrowing it was
# considered and rejected in design review: the audience defaults pair widths
# like s7+s5 and s8+s4, and a smaller set would leave a person unable to rebuild
# the default they started from.
DashboardWidgetSpan = Literal["s3", "s4", "s5", "s6", "s7", "s8", "s12"]
SPANS: frozenset[str] = frozenset(get_args(DashboardWidgetSpan))

# The closed set of card heights, in fixed grid rows. Height is optional on a
# placement: absent means "the widget's default height", so an arrangement
# saved before heights existed keeps rendering unchanged.
DashboardWidgetRows = Literal["r2", "r3", "r4", "r5", "r6"]
ROWS: frozenset[str] = frozenset(get_args(DashboardWidgetRows))

# The window presets a card may pin itself to, mirroring `PeriodPreset` in
# `frontend/src/lib/dashboard/period.ts`. A card with none follows the page's
# own filter, which is what nearly every card does.
DashboardWidgetPeriod = Literal["1d", "7d", "30d", "90d", "tm", "lm"]
PERIODS: frozenset[str] = frozenset(get_args(DashboardWidgetPeriod))

# Every presentation any widget can draw in, unioned. Which widget offers which
# is the frontend registry's table (`WIDGETS[id].options.styles`); this is only
# the boundary check that a stored style is a word this build knows at all.
WIDGET_STYLES: frozenset[str] = frozenset(
    {
        "area",
        "bars",
        "donut",
        "list",
        "meter",
        "table",
        "tiles",
    }
)

# A section divider's accent. "neutral" is the absence of a colour — a plain
# heading — so it is the default. The named presets mirror `ACCENT_PRESETS` in
# the frontend registry; beyond them a person may pick any colour, stored as a
# `#rrggbb` hex, so the accepted value is the presets, "neutral", or a hex —
# never an arbitrary string that would render as no colour and read as a bug.
ACCENT_PRESETS: frozenset[str] = frozenset({"violet", "blue", "green", "amber", "rose"})
_ACCENT_HEX = re.compile(r"^#[0-9a-f]{6}$")


def _normalise_accent(value: str) -> str:
    """Validate and canonicalise an accent, lower-casing a hex; reject the rest."""
    lowered = value.lower()
    if lowered == "neutral" or lowered in ACCENT_PRESETS or _ACCENT_HEX.match(lowered):
        return lowered
    raise ValueError(f"invalid dashboard section accent: {value!r}")


# Every widget the dashboard can place, by its stable registry id. Persisted, so
# the ids are a contract; kept equal to the frontend registry by a parity test.
WIDGET_IDS: frozenset[str] = frozenset(
    {
        "summary",
        "platform",
        "health",
        "top-orgs",
        "platform-ratings",
        "runs",
        "outcomes",
        "surfaces",
        "agents",
        "latency",
        "active-users",
        "top-people",
        "spend",
        "model-mix",
        "version-compare",
        "approvals",
        "recent-failures",
        "budget-headroom",
        "mcp-health",
        "knowledge-freshness",
        "members",
        "org-ratings",
        "my-agents",
        "conversations",
        "my-activity",
        "my-top-agents",
        "my-quality",
        "shared-with-you",
        "sandbox-capacity",
        "sandbox-sessions",
        "sandbox-policy",
        "channels",
        "knowledge",
        "activity-rhythm",
        "routines",
    }
)

# A saved layout is bounded so a single write cannot store an unbounded blob.
# The largest audience default is around twenty cards; the ceiling leaves room
# to place a few widgets twice without inviting abuse.
MAX_ENTRIES = 60

# Named presets are bounded the same way: enough for a person to keep one per
# working context, low enough that a script cannot fill the table.
MAX_PRESETS = 20


class WidgetOptions(BaseSchema):
    """A card's own settings, overriding what the page decides for every card.

    The page carries one time filter; a card carrying its own is how "runs over
    the last 90 days" sits beside "runs this month" on one dashboard. The two
    narrowing ids do the same for *which rows*: one agent, or one colleague.
    They reach `GET /stats/usage` as its `agent_id` / `user_id` filters and are
    refused there if the caller may not read what they ask for - a stored option
    is a request, never an authorisation.

    `style` is which presentation the widget draws in - a donut instead of bars.
    Validated against the union of every style any widget declares rather than
    against this widget's own list: the per-widget matrix is the frontend
    registry's, and mirroring it here would be two copies of a table that
    changes whenever a card grows a variant. A style this build does not know
    is refused; a style the wrong widget was given falls back to that widget's
    default at render time, the same forgiveness a retired widget id gets.
    """

    period: DashboardWidgetPeriod | None = None
    style: str | None = Field(default=None, max_length=32)
    agent_id: UUID | None = None
    user_id: UUID | None = None

    @field_validator("style")
    @classmethod
    def _known_style(cls, value: str | None) -> str | None:
        if value is not None and value not in WIDGET_STYLES:
            raise ValueError(f"unknown dashboard widget style: {value!r}")
        return value


class WidgetPlacement(BaseSchema):
    """One placed widget, as accepted on write — validated against the registry.

    `span` and `rows` are the card's width and height, both from the closed grid
    sets; `rows` is optional so an arrangement saved before heights existed keeps
    rendering at the widget's default height. `options` is the card's own
    settings, absent on a card that simply follows the page.
    """

    kind: Literal["widget"] = "widget"
    widget: str = Field(..., max_length=64)
    span: DashboardWidgetSpan
    rows: DashboardWidgetRows | None = None
    options: WidgetOptions | None = None

    @field_validator("widget")
    @classmethod
    def _known_widget(cls, value: str) -> str:
        if value not in WIDGET_IDS:
            raise ValueError(f"unknown dashboard widget id: {value!r}")
        return value


class SectionDivider(BaseSchema):
    """A full-width heading that splits an arrangement into coloured sections.

    Unlike a widget, a divider is not gated — it names a group rather than
    exposing data — so it carries no registry id, only a free-text `label` the
    person typed, an `accent` (a named preset, a custom `#rrggbb` hex, or
    "neutral" for none), and `collapsed`, which folds the section to its heading.
    An empty label is valid: a bare coloured rule with no caption is a legitimate
    way to break a long dashboard into bands.
    """

    kind: Literal["section"]
    label: str = Field(default="", max_length=60)
    accent: str = Field(default="neutral", max_length=32)
    collapsed: bool = False

    @field_validator("accent")
    @classmethod
    def _valid_accent(cls, value: str) -> str:
        return _normalise_accent(value)


def _entry_discriminator(value: Any) -> str:
    """Route an entry to its member — anything not tagged `section` is a widget.

    Forgiving on purpose: an arrangement saved before dividers existed has
    entries with no `kind`, and those are widgets, not a validation error.
    """
    raw = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return "section" if raw == "section" else "widget"


# One entry as accepted on write: a validated widget or a section divider.
LayoutEntryIn = Annotated[
    Annotated[WidgetPlacement, Tag("widget")] | Annotated[SectionDivider, Tag("section")],
    Discriminator(_entry_discriminator),
]


class StoredWidgetPlacement(BaseSchema):
    """One entry, as returned on read — permissive by design.

    A `widget` a later release retired is still handed back verbatim; the
    frontend registry is the authority on what can render, and it drops an id it
    does not know rather than the API refusing the whole row. The divider fields
    (`label`, `accent`, `collapsed`) and `widget`/`span` are all optional here
    because a stored entry is one kind or the other, and read never re-validates
    which.
    """

    kind: str = "widget"
    widget: str | None = None
    span: str | None = None
    rows: str | None = None
    label: str | None = None
    accent: str | None = None
    collapsed: bool = False
    # Handed back as it was stored, for the same reason `widget` is: a card
    # pinned to an agent that has since been deleted, or to a style a later
    # release renamed, must not take the whole arrangement down with it. The
    # frontend drops what it cannot honour.
    options: dict[str, Any] | None = None


class DashboardLayoutUpdate(BaseSchema):
    """Replace the caller's saved arrangement for the active organization.

    An empty `entries` list is valid: it is a person who has hidden every
    card, which the dashboard renders as an offer to reset rather than a broken
    page. Absence of a saved layout entirely is a different state — the audience
    default — reached by `DELETE`, not by saving an empty list.
    """

    entries: list[LayoutEntryIn] = Field(..., max_length=MAX_ENTRIES)


class DashboardLayoutRead(BaseSchema, TimestampSchema):
    id: UUID
    organization_id: UUID
    entries: list[StoredWidgetPlacement]


class DashboardPresetCreate(BaseSchema):
    """Save the caller's arrangement under a name they can switch back to.

    Creating a preset does not change what the dashboard shows — applying one
    does, by writing its entries as the active arrangement. The name is unique
    per person per organization, so "Monday review" can exist once in each
    organization the person belongs to.
    """

    name: str = Field(..., min_length=1, max_length=60)
    entries: list[LayoutEntryIn] = Field(..., max_length=MAX_ENTRIES)


class DashboardPresetRead(BaseSchema, TimestampSchema):
    id: UUID
    organization_id: UUID
    name: str
    entries: list[StoredWidgetPlacement]


class DashboardPresetList(BaseSchema):
    items: list[DashboardPresetRead]
    total: int
