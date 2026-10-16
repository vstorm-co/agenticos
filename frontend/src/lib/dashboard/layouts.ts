/**
 * Who sees which sections, in what order, at what widths.
 *
 * A layout is data: an ordered list of sections, each an ordered list of
 * `{widget, span, titleKey?}` entries. Span and title ride the entry rather
 * than a widget-keyed lookup, so one widget can appear twice on a page with
 * different widths and names (the viewer's "Agents shared with you" is the
 * my-agents widget under another title).
 *
 * The layout only proposes; the registry's gates dispose. The page filters
 * every entry through its widget's gate, and a section whose entries all fail
 * renders nothing - not even its heading.
 */

import type { Permission } from "@/types/permissions";
import type { PeriodPreset } from "./period";
import { WIDGETS, type Rows, type SectionAccent, type Span, type WidgetId } from "./registry";

/**
 * What one card overrides about itself, against a page that decides for all of
 * them.
 *
 * Absent on nearly every placement, and that is the default worth protecting: a
 * dashboard whose cards each answer about a different window is a dashboard
 * nobody can read across. These exist for the card that genuinely asks a
 * different question - the ninety-day trend beside the month's totals, the one
 * agent under review - and the card says so in its own header when it does.
 *
 * Which of these a widget accepts is its `options` in the registry; anything it
 * does not declare is dropped on read, so a knob that was removed from a widget
 * stops being sent to the API rather than lingering invisibly in a saved row.
 */
export interface WidgetOptions {
  /** Its own window, instead of the page's filter. */
  period?: PeriodPreset;
  /** Which presentation to draw in - one of the widget's declared styles. */
  style?: string;
  /** Narrow every number on this card to one agent. */
  agentId?: string;
  /** Narrow every number on this card to one person. */
  userId?: string;
  /**
   * Narrow every number on this card to one group's members. Never stored: the
   * page's group view sets it on every card it renders, after the saved
   * options are sanitized, so no widget declares it.
   */
  groupId?: string;
}

export interface LayoutEntry {
  /**
   * The entry kind, discriminating this widget placement from a
   * {@link DividerEntry}. Optional and defaulting to `"widget"` so the audience
   * defaults below — and every arrangement saved before dividers existed — read
   * as widgets without carrying the tag.
   */
  kind?: "widget";
  widget: WidgetId;
  span: Span;
  /**
   * Card height in fixed grid rows. Optional only for an arrangement saved
   * before heights existed - `sanitizeEntries` fills those in from the widget's
   * default, and the shipped default below sets every one explicitly.
   */
  rows?: Rows;
  /** i18n key under `dashboard`, overriding the widget's default title. */
  titleKey?: string;
  /** What this card overrides about itself. Absent = it follows the page. */
  options?: WidgetOptions;
}

/**
 * A section divider: a full-width heading a person drops into their own
 * arrangement to break it into labelled, colour-tinted bands. It is not a
 * widget — it exposes no data and has no gate — so it carries only a free-text
 * label, an accent (a preset name, a custom `#rrggbb` hex, or neutral) and a
 * `collapsed` flag folding the section down to its heading, never a registry id.
 */
export interface DividerEntry {
  kind: "section";
  /** The free-text caption the person typed; may be empty (a bare rule). */
  label: string;
  accent: SectionAccent;
  /** Folded to just the heading on the page; the cards are hidden until reopened. */
  collapsed?: boolean;
}

/** One item in an arrangement: a widget placement or a section divider. */
export type LayoutItem = LayoutEntry | DividerEntry;

/** Narrow a {@link LayoutItem} to a section divider. */
export function isDivider(item: LayoutItem): item is DividerEntry {
  return item.kind === "section";
}

/** Narrow a {@link LayoutItem} to a widget placement. */
export function isWidget(item: LayoutItem): item is LayoutEntry {
  return item.kind !== "section";
}

export interface SectionDef {
  id: string;
  /** i18n key under `dashboard.sections`, or null for an untitled section. */
  titleKey: string | null;
  /**
   * A literal heading, used in place of `titleKey` for the sections a person's
   * own dividers create — those carry the text the person typed, not a key into
   * the catalog. Absent on the curated defaults, which are translated.
   */
  title?: string;
  /** The divider's colour, tinting this section's cards. Absent = neutral. */
  accent?: SectionAccent;
  /** Whether this section is folded to its heading — a custom divider's flag. */
  collapsed?: boolean;
  entries: LayoutEntry[];
}

export type AudienceId = "app_admin" | "steward" | "builder" | "operator" | "member" | "viewer";

/**
 * Role to audience. The app admin outranks the role; an unknown role - a
 * future custom one - lands on the member layout, the narrowest that still
 * shows the person their own work.
 */
export function resolveAudience(role: string, isAppAdmin: boolean): AudienceId {
  if (isAppAdmin) return "app_admin";
  switch (role) {
    case "owner":
    case "admin":
      return "steward";
    case "builder":
      return "builder";
    case "operator":
      return "operator";
    case "viewer":
      return "viewer";
    default:
      return "member";
  }
}

/**
 * Span to grid class. Literal strings so Tailwind's scanner sees them; below
 * `lg` everything stacks full-width. There is deliberately no span-to-pixels
 * table anywhere - charts measure themselves.
 */
export const SPAN_CLASS: Record<Span, string> = {
  s3: "lg:col-span-3",
  s4: "lg:col-span-4",
  s5: "lg:col-span-5",
  s6: "lg:col-span-6",
  s7: "lg:col-span-7",
  s8: "lg:col-span-8",
  s12: "lg:col-span-12",
};

/**
 * Row to grid class, the height counterpart of `SPAN_CLASS`. Literal strings so
 * Tailwind's scanner sees them; below `lg` every card stacks at its natural
 * height, so a `row-span` only bites where cards share a row.
 */
export const ROW_CLASS: Record<Rows, string> = {
  r2: "lg:row-span-2",
  r3: "lg:row-span-3",
  r4: "lg:row-span-4",
  r5: "lg:row-span-5",
  r6: "lg:row-span-6",
};

/**
 * The grid every arrangement renders in - the shipped default, a person's own,
 * and the editor between them.
 *
 * One grid, because a height only means something against a fixed row unit: it
 * pins the unit so a card's chosen height is the same number of pixels wherever
 * it sits, and `grid-flow-row-dense` lets a short card backfill the gap a tall
 * neighbour leaves. `SPAN_CLASS` and `ROW_CLASS` on each cell then place it in
 * two dimensions. The defaults used to auto-size instead, which meant the page
 * and the editor disagreed about the same layout.
 */
export const ARRANGED_GRID_CLASS =
  "grid grid-cols-1 gap-4 lg:auto-rows-[5.5rem] lg:grid-cols-12 lg:grid-flow-row-dense";

/** The columns a span occupies, out of twelve — `s6` → 6. */
export function spanCols(span: Span): number {
  return Number(span.slice(1));
}

/** The rows a height occupies — `r3` → 3. */
export function rowCount(rows: Rows): number {
  return Number(rows.slice(1));
}

/** Widths in ascending order, for stepping and snapping. */
export const SPAN_ORDER: Span[] = ["s3", "s4", "s5", "s6", "s7", "s8", "s12"];

/** Heights in ascending order, for stepping and snapping. */
export const ROW_ORDER: Rows[] = ["r2", "r3", "r4", "r5", "r6"];

function stepInOrder<T>(order: T[], value: T, direction: -1 | 1): T {
  const index = order.indexOf(value);
  const next = Math.min(Math.max(index + direction, 0), order.length - 1);
  return order[next] as T;
}

/** The next wider or narrower width, clamped at the ends of the closed set. */
export function stepSpan(span: Span, direction: -1 | 1): Span {
  return stepInOrder(SPAN_ORDER, span, direction);
}

/** The next taller or shorter height, clamped at the ends of the closed set. */
export function stepRows(rows: Rows, direction: -1 | 1): Rows {
  return stepInOrder(ROW_ORDER, rows, direction);
}

function nearest<T>(order: T[], count: number, size: (value: T) => number): T {
  let best = order[0] as T;
  let bestGap = Math.abs(size(best) - count);
  for (const value of order) {
    const gap = Math.abs(size(value) - count);
    if (gap < bestGap) {
      best = value;
      bestGap = gap;
    }
  }
  return best;
}

/** The allowed width closest to a column count — for snapping a pointer resize. */
export function nearestSpan(columns: number): Span {
  return nearest(SPAN_ORDER, columns, spanCols);
}

/** The allowed height closest to a row count — for snapping a pointer resize. */
export function nearestRows(rows: number): Rows {
  return nearest(ROW_ORDER, rows, rowCount);
}

/**
 * The organization view's arrangement, whatever the reader's role.
 *
 * One list rather than six curated ones, and it is not a simplification: the
 * layout only *proposes*, and `visibleSections` below disposes. Six
 * hand-written variants said the same thing a permission already says, and
 * drifted from each other every time a widget was added to one of them. A
 * person's own cards and the deployment's are views of their own (`viewLayout`)
 * rather than bands at the foot of this one.
 *
 * Every placement carries its height as well as its width, because both were
 * chosen on a real screen with a month of real-shaped data in the cards. That
 * is also why the page renders a default in the same fixed-row grid as an
 * arranged one: a height nobody can see is not a default anybody chose.
 *
 * **It shows the cards that answer with data, not every card there is.** The
 * catalog holds the rest - integrations, channels, routines, sandboxes,
 * departments - and each is one click away in Customize. On the default they
 * were mostly empty states: in an organization that had not connected an MCP
 * server or a channel, half the page said "nothing here", and the charts that
 * did have something to say began two screens down.
 *
 * The order inside a band is the order it was arranged in, and it is the rule
 * the whole page is built on - a row holds cards of comparable natural height,
 * and a chart never sits beside a status list it dwarfs.
 */
const DEFAULT_SECTIONS: SectionDef[] = [
  // Untitled, and first: the four figures, the runs behind them day by day and
  // how those runs ended. It is the answer the rest of the page is the detail
  // of, so it fills the first screen on its own.
  {
    id: "overview",
    titleKey: null,
    entries: [
      { widget: "summary", span: "s12", rows: "r3" },
      { widget: "runs", span: "s8", rows: "r4" },
      { widget: "outcomes", span: "s4", rows: "r4" },
    ],
  },
  // What a person can act on now. Kept to four cards that are short when there
  // is nothing to do - an approval queue, the failures, the budgets and the
  // notifications - and the notifications are the one card everybody sees.
  {
    id: "attention",
    titleKey: "attention",
    entries: [
      { widget: "approvals", span: "s6", rows: "r3" },
      { widget: "recent-failures", span: "s6", rows: "r3" },
      { widget: "budget-headroom", span: "s6", rows: "r3" },
      { widget: "notifications", span: "s6", rows: "r3" },
    ],
  },
  {
    id: "usage",
    titleKey: "usage",
    entries: [
      { widget: "agents", span: "s6", rows: "r3" },
      { widget: "spend", span: "s6", rows: "r3" },
      // Eight columns are enough for twenty-four hours, and the channel list
      // beside it is about as tall as seven days are.
      { widget: "activity-rhythm", span: "s8", rows: "r4" },
      { widget: "surfaces", span: "s4", rows: "r4" },
      { widget: "model-mix", span: "s4", rows: "r3" },
      { widget: "latency", span: "s4", rows: "r3" },
      { widget: "org-ratings", span: "s4", rows: "r3" },
      { widget: "top-people", span: "s12", rows: "r4" },
    ],
  },
];

/**
 * A person's own page: their agents, their threads, their runs, and what is
 * waiting on them. The view a member without `runs:view` opens on, and one
 * click away for everybody else.
 */
const ME_SECTIONS: SectionDef[] = [
  {
    id: "workspace",
    titleKey: null,
    entries: [
      // The four figures first: what ran, what finished, what waits on you and
      // what it cost, each in its own colour - the answer the rest is detail of.
      // It replaced the activity chart, which drew the same runs a second time.
      { widget: "my-summary", span: "s12", rows: "r2" },
      // Then what a person acts on: the calls waiting on them beside the
      // conversations they left open. The queue sat at the foot of the page,
      // under three cards of history, which is the wrong way round.
      { widget: "approvals", span: "s6", rows: "r3" },
      { widget: "conversations", span: "s6", rows: "r3" },
      { widget: "my-agents", span: "s6", rows: "r3" },
      { widget: "my-top-agents", span: "s6", rows: "r3" },
      // Three rows like the pair above: two left the quality chart a sliver
      // under its figure and legend, which said nothing either.
      { widget: "my-quality", span: "s6", rows: "r3" },
      { widget: "shared-with-you", span: "s6", rows: "r3" },
      // What agents drew for them lately, as pictures: the one card here that is
      // something to look at rather than a list to read.
      { widget: "recent-visuals", span: "s12", rows: "r3" },
    ],
  },
  {
    id: "attention",
    titleKey: "attention",
    entries: [{ widget: "notifications", span: "s12", rows: "r2" }],
  },
];

/**
 * One group's members, the cards that can be narrowed to them - every one of
 * these reads `/stats/usage`, which takes a `group_id`. Ratings, approvals and
 * failures are the organization's and are left to its view rather than shown
 * here unnarrowed under a group's name.
 */
const GROUP_SECTIONS: SectionDef[] = [
  {
    id: "overview",
    titleKey: null,
    entries: [
      { widget: "summary", span: "s12", rows: "r3" },
      { widget: "runs", span: "s8", rows: "r4" },
      { widget: "outcomes", span: "s4", rows: "r4" },
    ],
  },
  {
    id: "usage",
    titleKey: "usage",
    entries: [
      { widget: "agents", span: "s6", rows: "r3" },
      { widget: "spend", span: "s6", rows: "r3" },
      { widget: "activity-rhythm", span: "s8", rows: "r4" },
      { widget: "surfaces", span: "s4", rows: "r4" },
      { widget: "model-mix", span: "s6", rows: "r3" },
      { widget: "latency", span: "s6", rows: "r3" },
      { widget: "top-people", span: "s12", rows: "r4" },
    ],
  },
];

/** The host itself, for a deployment admin: every organization at once. */
const DEPLOYMENT_SECTIONS: SectionDef[] = [
  {
    id: "deployment",
    titleKey: null,
    entries: [
      { widget: "platform", span: "s6", rows: "r2" },
      { widget: "health", span: "s6", rows: "r2" },
      { widget: "top-orgs", span: "s6", rows: "r3" },
      { widget: "platform-ratings", span: "s6", rows: "r3" },
    ],
  },
];

/**
 * Which dashboard is on screen. The organization's is the arrangeable one -
 * a person's saved layout and presets are an arrangement of it; the other
 * three are fixed pages, each made of the cards that answer its question.
 */
export type DashboardView = "me" | "org" | "group" | "deployment";

export const DASHBOARD_VIEWS: readonly DashboardView[] = ["me", "org", "group", "deployment"];

/**
 * The same arrangement, with the agents card renamed for a viewer.
 *
 * A viewer's `my-agents` lists what was *shared with them* (`myAgentsPolicy`
 * narrows it), so calling those agents theirs is the one place the shared list
 * would say something untrue. It is the only per-audience difference left.
 */
function forViewer(sections: SectionDef[]): SectionDef[] {
  return sections.map((section) => ({
    ...section,
    entries: section.entries.map((entry) =>
      entry.widget === "my-agents"
        ? { ...entry, titleKey: "widgets.my-agents.sharedTitle" }
        : entry,
    ),
  }));
}

/** The organization view's default, for every audience - the gate is what differs. */
export const LAYOUTS: Record<AudienceId, SectionDef[]> = {
  app_admin: DEFAULT_SECTIONS,
  steward: DEFAULT_SECTIONS,
  operator: DEFAULT_SECTIONS,
  builder: DEFAULT_SECTIONS,
  member: DEFAULT_SECTIONS,
  viewer: DEFAULT_SECTIONS,
};

/** The fixed layout of a view other than the organization's arrangeable one. */
export function viewLayout(
  view: Exclude<DashboardView, "org">,
  audience: AudienceId,
): SectionDef[] {
  switch (view) {
    case "me":
      return audience === "viewer" ? forViewer(ME_SECTIONS) : ME_SECTIONS;
    case "group":
      return GROUP_SECTIONS;
    case "deployment":
      return DEPLOYMENT_SECTIONS;
  }
}

/**
 * A section list with every entry the caller may not see removed, and every
 * section that ended up empty dropped - heading included. This is the whole of
 * the page's authorization, and it runs **last**, on whatever layout it is
 * handed: the audience default, or a person's own saved arrangement. A stored
 * preference can reorder or hide, but the gate here is what stops it revealing -
 * a widget that fails its gate is never mounted, so its queries are never
 * issued either, whichever layer put it in the list.
 */
export function visibleSections(
  sections: SectionDef[],
  can: (permission: Permission) => boolean,
  isAppAdmin: boolean,
): SectionDef[] {
  return sections
    .map((section) => ({
      ...section,
      entries: section.entries.filter((entry) => WIDGETS[entry.widget].gate(can, isAppAdmin)),
    }))
    .filter((section) => section.entries.length > 0);
}
