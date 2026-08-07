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
import { Perm, type Permission } from "@/types/permissions";

export type WidgetId =
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
  | "shared-with-you";

/** The closed set of card widths the grid supports (12 columns). */
export type Span = "s3" | "s4" | "s5" | "s6" | "s7" | "s8" | "s12";

/** Whether this caller may see a widget. Injected, never read off globals. */
export type Gate = (can: (permission: Permission) => boolean, isAppAdmin: boolean) => boolean;

export interface WidgetDef {
  id: WidgetId;
  gate: Gate;
  defaultSpan: Span;
  /** Where "see all" points - a page that already exists. Absent = no link. */
  seeAll?: string;
}

const adminOnly: Gate = (_can, isAppAdmin) => isAppAdmin;
const holds =
  (permission: Permission): Gate =>
  (can) =>
    can(permission);

export const WIDGETS: Record<WidgetId, WidgetDef> = {
  platform: { id: "platform", gate: adminOnly, defaultSpan: "s8", seeAll: ROUTES.ADMIN },
  health: { id: "health", gate: adminOnly, defaultSpan: "s4", seeAll: ROUTES.ADMIN_SYSTEM },
  "top-orgs": { id: "top-orgs", gate: adminOnly, defaultSpan: "s7", seeAll: ROUTES.ADMIN },
  "platform-ratings": {
    id: "platform-ratings",
    gate: adminOnly,
    defaultSpan: "s5",
    seeAll: ROUTES.ADMIN_RATINGS,
  },
  runs: { id: "runs", gate: holds(Perm.runsView), defaultSpan: "s8", seeAll: ROUTES.RUNS },
  outcomes: { id: "outcomes", gate: holds(Perm.runsView), defaultSpan: "s4", seeAll: ROUTES.RUNS },
  surfaces: { id: "surfaces", gate: holds(Perm.runsView), defaultSpan: "s6" },
  agents: { id: "agents", gate: holds(Perm.runsView), defaultSpan: "s6", seeAll: ROUTES.AGENTS },
  latency: { id: "latency", gate: holds(Perm.runsView), defaultSpan: "s4" },
  "active-users": { id: "active-users", gate: holds(Perm.runsView), defaultSpan: "s8" },
  // The only card that answers with names. Same gate as the count it sits
  // under, which means builder and operator see it too - the card says so
  // rather than the layouts quietly withholding it from some of them.
  "top-people": { id: "top-people", gate: holds(Perm.runsView), defaultSpan: "s12" },
  spend: { id: "spend", gate: holds(Perm.runsView), defaultSpan: "s6", seeAll: ROUTES.RUNS },
  "model-mix": { id: "model-mix", gate: holds(Perm.runsView), defaultSpan: "s6" },
  "version-compare": {
    id: "version-compare",
    gate: holds(Perm.runsView),
    defaultSpan: "s6",
    seeAll: ROUTES.AGENTS,
  },
  approvals: {
    id: "approvals",
    gate: holds(Perm.approvalsDecide),
    defaultSpan: "s7",
    seeAll: ROUTES.RUNS,
  },
  "recent-failures": {
    id: "recent-failures",
    gate: holds(Perm.runsView),
    defaultSpan: "s5",
    seeAll: ROUTES.RUNS,
  },
  // No seeAll here: the page worth reaching from the headroom card is the
  // organization's settings, whose path carries an id this catalog has no
  // access to, so the widget computes its own.
  "budget-headroom": { id: "budget-headroom", gate: holds(Perm.runsView), defaultSpan: "s4" },
  "mcp-health": {
    id: "mcp-health",
    gate: holds(Perm.mcpManage),
    defaultSpan: "s4",
    seeAll: ROUTES.MCP_SERVERS,
  },
  "knowledge-freshness": {
    id: "knowledge-freshness",
    gate: holds(Perm.collectionsView),
    defaultSpan: "s4",
    seeAll: ROUTES.RAG,
  },
  members: {
    id: "members",
    gate: holds(Perm.membersManage),
    defaultSpan: "s6",
    seeAll: ROUTES.ORGS,
  },
  "org-ratings": { id: "org-ratings", gate: holds(Perm.runsView), defaultSpan: "s6" },
  "my-agents": {
    id: "my-agents",
    gate: holds(Perm.agentsView),
    defaultSpan: "s6",
    seeAll: ROUTES.AGENTS,
  },
  conversations: {
    id: "conversations",
    gate: holds(Perm.agentsRun),
    defaultSpan: "s6",
    seeAll: ROUTES.CHAT,
  },
  "my-activity": { id: "my-activity", gate: holds(Perm.agentsRun), defaultSpan: "s12" },
  "my-top-agents": { id: "my-top-agents", gate: holds(Perm.agentsRun), defaultSpan: "s6" },
  "my-quality": { id: "my-quality", gate: holds(Perm.agentsRun), defaultSpan: "s6" },
  "shared-with-you": {
    id: "shared-with-you",
    gate: holds(Perm.agentsView),
    defaultSpan: "s4",
  },
};

export const WIDGET_IDS = Object.keys(WIDGETS) as WidgetId[];
