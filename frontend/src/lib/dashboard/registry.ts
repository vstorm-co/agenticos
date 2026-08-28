/**
 * The widget catalog: every card the dashboard can show, with its gate.
 *
 * Three rules, inherited from the design review, that must survive every
 * refactor:
 *
 * - A gate takes what it needs - `(can, isAppAdmin)` - never a closure over
 *   module state, so a widget is testable alone.
 * - Span and title ride the layout entry, not this catalog: the same widget
 *   may appear twice on one page with different spans and titles.
 * - Catalog metadata (default span, "see all" destination, i18n-keyed copy)
 *   is here from day one, because the future user-arranged dashboard picks
 *   from this list and retrofitting metadata is expensive.
 *
 * Copy lives in the `dashboard.widgets.<id>.*` i18n namespace, keyed by the
 * widget id - ids are stable registry keys, safe to persist and to translate.
 */

import { ROUTES } from "@/lib/constants";
import { runsHref } from "@/lib/runs/filter-params";
import { Perm, type Permission } from "@/types/permissions";

export type WidgetId =
  | "summary"
  | "platform"
  | "health"
  | "top-orgs"
  | "platform-ratings"
  | "runs"
  | "outcomes"
  | "surfaces"
  | "agents"
  | "latency"
  | "active-users"
  | "top-people"
  | "spend"
  | "model-mix"
  | "version-compare"
  | "approvals"
  | "recent-failures"
  | "budget-headroom"
  | "mcp-health"
  | "knowledge-freshness"
  | "members"
  | "org-ratings"
  | "my-agents"
  | "conversations"
  | "my-activity"
  | "my-top-agents"
  | "my-quality"
  | "shared-with-you"
  | "sandbox-capacity"
  | "sandbox-sessions"
  | "sandbox-policy"
  | "channels"
  | "knowledge"
  | "activity-rhythm"
  | "routines";

/** The closed set of card widths the grid supports (12 columns). */
export type Span = "s3" | "s4" | "s5" | "s6" | "s7" | "s8" | "s12";

/**
 * The family a widget belongs to, used only to group the "add a widget"
 * catalog so a long list is browsable. It is not a gate and not a layout - a
 * widget's audience is its `gate`, and where it sits on a page is its layout
 * entry; this is purely how the picker sorts its shelves.
 */
export type WidgetCategory =
  "platform" | "attention" | "usage" | "people" | "sandboxes" | "workspace";

/** The order the picker shows its groups in, broad-to-personal. */
export const CATEGORY_ORDER: WidgetCategory[] = [
  "platform",
  "attention",
  "usage",
  "people",
  "sandboxes",
  "workspace",
];

/**
 * A section divider's accent: `"neutral"` (no colour — a plain heading that
 * renders like the curated sections), one of the named {@link ACCENT_PRESETS},
 * or a custom `#rrggbb` hex the person picked. Stored as a plain string so a
 * custom colour round-trips; the backend accepts exactly this set
 * (`_normalise_accent` in `backend/app/schemas/dashboard_layout.py`).
 */
export type SectionAccent = string;

/** The named accents the editor offers as one-click swatches. */
export const ACCENT_PRESETS = ["violet", "blue", "green", "amber", "rose"] as const;
export type AccentPreset = (typeof ACCENT_PRESETS)[number];

const ACCENT_PRESET_SET = new Set<string>(ACCENT_PRESETS);
const ACCENT_HEX = /^#[0-9a-f]{6}$/i;

/** Whether an accent paints anything — a preset or a valid hex, not neutral. */
export function isAccentColour(accent: string | null | undefined): boolean {
  return (
    !!accent && accent !== "neutral" && (ACCENT_PRESET_SET.has(accent) || ACCENT_HEX.test(accent))
  );
}

/** Whether an accent is one of the named presets (it carries its own class). */
export function isPresetAccent(accent: string): accent is AccentPreset {
  return ACCENT_PRESET_SET.has(accent);
}

/**
 * Canonicalise a stored accent: keep neutral, a known preset, or a `#rrggbb`
 * hex (lower-cased); anything the palette no longer knows falls back to
 * neutral, the forgiving read `sanitizeEntries` gives every stored field.
 */
export function normaliseAccent(accent: string | null | undefined): SectionAccent {
  if (!accent || accent === "neutral") return "neutral";
  if (ACCENT_PRESET_SET.has(accent)) return accent;
  return ACCENT_HEX.test(accent) ? accent.toLowerCase() : "neutral";
}

/**
 * How to paint an accent. A preset contributes its `dash-accent-*` class (which
 * sets `--dash-solid`); a custom hex sets `--dash-solid` inline. Neutral paints
 * nothing. The consuming classes (`dash-section-accent`, `dash-tile-accent`,
 * `dash-swatch`) read `--dash-solid` either way, so a caller pairs one of them
 * with this decoration and never branches on preset-versus-custom itself.
 */
export interface AccentDecoration {
  className: string;
  style?: Record<string, string>;
}
export function accentDecoration(accent: string): AccentDecoration {
  if (isPresetAccent(accent)) return { className: `dash-accent-${accent}` };
  if (ACCENT_HEX.test(accent))
    return { className: "", style: { "--dash-solid": accent.toLowerCase() } };
  return { className: "" };
}

/**
 * The closed set of card heights, in fixed grid rows. Heights only apply to a
 * person's own arrangement — the audience defaults keep auto-sizing — so the
 * scale starts at two rows (one is too short for any card) and stops where a
 * card would outgrow a laptop viewport.
 */
export type Rows = "r2" | "r3" | "r4" | "r5" | "r6";

/**
 * Every presentation any widget can draw in.
 *
 * One union rather than a per-widget one, because it is also the backend's
 * boundary check (`WIDGET_STYLES` in `app/schemas/dashboard_layout.py`, kept
 * equal by `tests/test_dashboard_registry.py`). Which of these a given widget
 * actually offers is {@link WidgetOptionSpec.styles} below - the first entry
 * there is that widget's default, and a stored style it does not offer falls
 * back to it rather than rendering nothing.
 */
export type WidgetStyle = "area" | "bars" | "donut" | "list" | "meter" | "table" | "tiles";

/**
 * What a person may change about one card, declared by the widget itself.
 *
 * The page carries one time filter and one organization; a card carrying its
 * own window - or its own agent - is how "the last 90 days for jarvis" sits
 * beside "this month, everything" on one dashboard. A widget that declares
 * nothing here offers no knobs, which is the honest answer for a card whose
 * data has no window and no subject (the health probes, the sandbox host).
 */
export interface WidgetOptionSpec {
  /** The card may pin its own window instead of following the page filter. */
  period?: boolean;
  /** Presentations this widget can draw in. The first is its default. */
  styles?: readonly WidgetStyle[];
  /** The card may be narrowed to one agent. */
  agent?: boolean;
  /** The card may be narrowed to one person. */
  person?: boolean;
}

/** Whether this caller may see a widget. Injected, never read off globals. */
export type Gate = (can: (permission: Permission) => boolean, isAppAdmin: boolean) => boolean;

export interface WidgetDef {
  id: WidgetId;
  gate: Gate;
  defaultSpan: Span;
  /** The height a placement gets when it does not carry one of its own. */
  defaultRows: Rows;
  /** Which shelf the picker files this card under. Not a gate, not a layout. */
  category: WidgetCategory;
  /** Where "see all" points - a page that already exists. Absent = no link. */
  seeAll?: string;
  /** What a person may change about this card. Absent = nothing. */
  options?: WidgetOptionSpec;
}

/** The knobs a widget offers, or an empty spec for one that offers none. */
export function optionSpec(id: WidgetId): WidgetOptionSpec {
  return WIDGETS[id].options ?? {};
}

/**
 * The style to draw `id` in, given what a placement asked for.
 *
 * A style the widget does not offer answers with its default: a stored option
 * outlives the release that wrote it, and a card that renders the wrong chart
 * is better than a card that renders nothing.
 */
export function resolveStyle(id: WidgetId, asked: string | undefined): WidgetStyle | null {
  const styles = optionSpec(id).styles;
  if (!styles || styles.length === 0) return null;
  return styles.includes(asked as WidgetStyle) ? (asked as WidgetStyle) : (styles[0] ?? null);
}

const adminOnly: Gate = (_can, isAppAdmin) => isAppAdmin;
const holds =
  (permission: Permission): Gate =>
  (can) =>
    can(permission);

export const WIDGETS: Record<WidgetId, WidgetDef> = {
  "activity-rhythm": {
    id: "activity-rhythm",
    gate: holds(Perm.runsView),
    defaultSpan: "s12",
    defaultRows: "r4",
    category: "usage",
    options: { period: true, agent: true, person: true },
    seeAll: ROUTES.RUNS,
  },
  routines: {
    id: "routines",
    // What `GET /triggers` itself demands. Not `runsView`: the outcome half of
    // each row is a run read and is fetched only when the caller holds that,
    // where the routines themselves - cadence, paused, next fire - need only to
    // be allowed to see the agents they hang off.
    gate: holds(Perm.agentsView),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "attention",
    seeAll: ROUTES.ROUTINES,
  },
  channels: {
    id: "channels",
    gate: holds(Perm.channelsManage),
    defaultSpan: "s4",
    defaultRows: "r3",
    category: "attention",
    seeAll: ROUTES.CHANNELS,
  },
  knowledge: {
    id: "knowledge",
    gate: holds(Perm.collectionsView),
    defaultSpan: "s4",
    defaultRows: "r2",
    category: "attention",
    seeAll: ROUTES.RAG,
  },
  summary: {
    id: "summary",
    gate: holds(Perm.runsView),
    defaultSpan: "s12",
    defaultRows: "r3",
    category: "usage",
    options: { period: true, agent: true, person: true },
    seeAll: ROUTES.RUNS,
  },
  // Counters and no series behind any of them, so two rows is the height: a
  // third was a hand's width of nothing under the numbers.
  platform: {
    id: "platform",
    gate: adminOnly,
    defaultSpan: "s8",
    defaultRows: "r2",
    category: "platform",
    // The people behind the counts. It pointed at `/admin`, which rendered
    // these same figures a second time and now redirects here anyway (#922).
    seeAll: ROUTES.ADMIN_USERS,
  },
  health: {
    id: "health",
    gate: adminOnly,
    defaultSpan: "s4",
    defaultRows: "r3",
    category: "platform",
    options: { styles: ["tiles", "list"] },
    seeAll: ROUTES.ADMIN_SYSTEM,
  },
  "top-orgs": {
    id: "top-orgs",
    gate: adminOnly,
    defaultSpan: "s7",
    defaultRows: "r3",
    category: "platform",
    // The whole tenant list, which is what "see all" means on a card showing
    // the largest few.
    seeAll: ROUTES.ADMIN_ORGANIZATIONS,
  },
  // No seeAll: the deployment-wide ratings page left with the admin overhaul -
  // ratings are read where the runs are, on the Activity page, per org.
  "platform-ratings": {
    id: "platform-ratings",
    gate: adminOnly,
    defaultSpan: "s5",
    defaultRows: "r2",
    category: "platform",
    options: { period: true },
  },
  runs: {
    id: "runs",
    gate: holds(Perm.runsView),
    defaultSpan: "s8",
    defaultRows: "r3",
    category: "usage",
    options: { period: true, agent: true, person: true, styles: ["area", "bars"] },
    seeAll: ROUTES.RUNS,
  },
  outcomes: {
    id: "outcomes",
    gate: holds(Perm.runsView),
    defaultSpan: "s4",
    defaultRows: "r3",
    category: "usage",
    options: { period: true, agent: true, person: true, styles: ["donut", "bars"] },
    seeAll: ROUTES.RUNS,
  },
  surfaces: {
    id: "surfaces",
    gate: holds(Perm.runsView),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "usage",
    options: { period: true, agent: true, person: true, styles: ["bars", "donut"] },
    seeAll: ROUTES.RUNS,
  },
  agents: {
    id: "agents",
    gate: holds(Perm.runsView),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "usage",
    options: { period: true, person: true },
    seeAll: ROUTES.AGENTS,
  },
  latency: {
    id: "latency",
    gate: holds(Perm.runsView),
    defaultSpan: "s4",
    defaultRows: "r2",
    category: "usage",
    options: { period: true, agent: true, person: true },
  },
  // One figure and the roster it is a share of - a narrow card, not a
  // two-thirds one, which is the width it was and the reason it sat beside
  // latency with an empty half.
  "active-users": {
    id: "active-users",
    gate: holds(Perm.runsView),
    defaultSpan: "s4",
    defaultRows: "r2",
    category: "usage",
    options: { period: true, agent: true },
    seeAll: ROUTES.RUNS,
  },
  // The only card that answers with names. Same gate as the count it sits
  // under, which means builder and operator see it too - the card says so
  // rather than the layouts quietly withholding it from some of them.
  "top-people": {
    id: "top-people",
    gate: holds(Perm.runsView),
    defaultSpan: "s12",
    defaultRows: "r3",
    category: "usage",
    options: { period: true, agent: true },
    seeAll: ROUTES.RUNS,
  },
  spend: {
    id: "spend",
    gate: holds(Perm.runsView),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "usage",
    options: { period: true, agent: true, person: true },
    seeAll: ROUTES.RUNS,
  },
  "model-mix": {
    id: "model-mix",
    gate: holds(Perm.runsView),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "usage",
    options: { period: true, agent: true, person: true, styles: ["bars", "donut"] },
    seeAll: ROUTES.RUNS,
  },
  "version-compare": {
    id: "version-compare",
    gate: holds(Perm.runsView),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "usage",
    options: { period: true },
    seeAll: ROUTES.AGENTS,
  },
  approvals: {
    id: "approvals",
    gate: holds(Perm.approvalsDecide),
    defaultSpan: "s7",
    defaultRows: "r3",
    category: "attention",
    // The queue, not the run history. "See all" on a card counting what is
    // waiting used to open Activity on Runs, where nothing can be decided -
    // the same wrong destination the approval alert had, for the same reason:
    // there was no URL for the tab until #934.
    seeAll: runsHref({ tab: "approvals" }),
  },
  "recent-failures": {
    id: "recent-failures",
    gate: holds(Perm.runsView),
    defaultSpan: "s5",
    defaultRows: "r3",
    category: "attention",
    seeAll: ROUTES.RUNS,
  },
  // No seeAll here: the page worth reaching from the headroom card is the
  // organization's settings, whose path carries an id this catalog has no
  // access to, so the widget computes its own.
  "budget-headroom": {
    id: "budget-headroom",
    gate: holds(Perm.runsView),
    defaultSpan: "s4",
    defaultRows: "r2",
    category: "attention",
  },
  "mcp-health": {
    id: "mcp-health",
    gate: holds(Perm.mcpManage),
    defaultSpan: "s4",
    defaultRows: "r2",
    category: "attention",
    seeAll: ROUTES.MCP_SERVERS,
  },
  "knowledge-freshness": {
    id: "knowledge-freshness",
    gate: holds(Perm.collectionsView),
    defaultSpan: "s4",
    defaultRows: "r2",
    category: "attention",
    seeAll: ROUTES.RAG,
  },
  members: {
    id: "members",
    gate: holds(Perm.membersManage),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "people",
    options: { styles: ["meter", "bars"] },
    seeAll: ROUTES.ORGS,
  },
  "org-ratings": {
    id: "org-ratings",
    gate: holds(Perm.runsView),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "usage",
    options: { period: true },
  },
  "my-agents": {
    id: "my-agents",
    gate: holds(Perm.agentsView),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "workspace",
    options: { period: true },
    seeAll: ROUTES.AGENTS,
  },
  conversations: {
    id: "conversations",
    gate: holds(Perm.agentsRun),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "workspace",
    seeAll: ROUTES.CHAT,
  },
  "my-activity": {
    id: "my-activity",
    gate: holds(Perm.agentsRun),
    defaultSpan: "s12",
    defaultRows: "r4",
    category: "workspace",
    options: { period: true },
  },
  "my-top-agents": {
    id: "my-top-agents",
    gate: holds(Perm.agentsRun),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "workspace",
    options: { period: true },
  },
  "my-quality": {
    id: "my-quality",
    gate: holds(Perm.agentsRun),
    defaultSpan: "s6",
    defaultRows: "r3",
    category: "workspace",
    options: { period: true },
  },
  "shared-with-you": {
    id: "shared-with-you",
    gate: holds(Perm.agentsView),
    defaultSpan: "s4",
    defaultRows: "r2",
    category: "workspace",
  },
  // The sandbox cards are read-only views of a host, so they gate on
  // `connections:view` - the watch-a-connection scope that reads its sessions
  // and ceilings without the manage authority that points a host somewhere or
  // attaches its credential. That is why an operator, who holds the read and not
  // the write, sees these.
  "sandbox-capacity": {
    id: "sandbox-capacity",
    gate: holds(Perm.connectionsView),
    defaultSpan: "s5",
    defaultRows: "r3",
    category: "sandboxes",
    seeAll: ROUTES.SANDBOXES,
  },
  "sandbox-sessions": {
    id: "sandbox-sessions",
    gate: holds(Perm.connectionsView),
    defaultSpan: "s12",
    defaultRows: "r4",
    category: "sandboxes",
    seeAll: ROUTES.SANDBOXES,
  },
  "sandbox-policy": {
    id: "sandbox-policy",
    gate: holds(Perm.connectionsView),
    defaultSpan: "s7",
    defaultRows: "r3",
    category: "sandboxes",
    seeAll: ROUTES.SANDBOXES,
  },
};

export const WIDGET_IDS = Object.keys(WIDGETS) as WidgetId[];
