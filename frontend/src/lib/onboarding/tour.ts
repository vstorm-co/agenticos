import { ROUTES } from "@/lib/constants";
import { Perm, type Permission } from "@/types/permissions";

/**
 * The builder is a detail view, so it has no static route of its own — every
 * agent's is `/agents/<its id>`. This identity stands in for all of them: a step
 * that lives on it carries `page: AGENT_BUILDER`, `pageKey` collapses any
 * `/agents/<id>` pathname onto it, and the engine resolves a concrete agent to
 * open when the walkthrough needs to enter one.
 */
export const AGENT_BUILDER = "agent-builder";

/** The knowledge-base detail view, `/rag/<id>`, collapsed to one identity the same way. */
export const KB_DETAIL = "kb-detail";

/**
 * The two organization detail routes, collapsed the same way. Unlike the builder
 * and the collection — one detail route each — an organization opens onto two,
 * `/orgs/<id>/members` and `/orgs/<id>/roles`, so it takes two identities chained
 * in one flow: the "?" walks the members page and then steps across into roles.
 */
export const ORG_MEMBERS = "org-members-detail";
export const ORG_ROLES = "org-roles-detail";

/**
 * The Settings section, `/settings/*`. Its four pages — profile, account,
 * notifications, slash-commands — share one tabbed layout, so one identity stands
 * in for all of them and a single "?" stop points at the tabs on whichever page
 * the reader opened it from.
 */
export const SETTINGS_DETAIL = "settings-detail";

/**
 * A workspace's file browser, `/workspaces/<id>`, collapsed the same way. Unlike a
 * seeded agent or collection there is no example to open from the list — a
 * workspace is one person's own agent output — so its stop is "?"-only help shown
 * in place, once the reader has opened one of their own.
 */
export const WORKSPACE_DETAIL = "workspace-detail";

/**
 * One stop on the guided tour.
 *
 * The engine (`components/onboarding`) gets the reader to `page`, optionally
 * clicks `activate` to reveal the section the step lives in, waits for
 * `[data-tour="<target>"]` to mount, then spotlights it with a driver.js popover
 * carrying `onboarding.steps.<id>.title` and `.body`. A step with no `target` is
 * an interstitial shown as a centered popover (welcome, finish); one with no
 * `page` stays on whatever page the tour reached, so the closing card does not
 * yank the reader back to the dashboard.
 *
 * `page` is a page *identity*, not always a route. Most steps name a real route
 * and the engine navigates there. A detail view has no route of its own — there
 * is one builder per agent — so its steps carry a pseudo-identity (`AGENT_BUILDER`)
 * that `pageKey` maps every concrete detail pathname onto, and the engine turns
 * back into a real URL by resolving an example to open. `activate` names another
 * `[data-tour="…"]` the engine clicks first: a tab whose panel holds the target,
 * so a step deep in the Builder's Toolbox tab reveals it before spotlighting.
 *
 * There are two readers of this list, and `inTour` is what tells them apart. The
 * first-run walkthrough is the *curated* pass — `inTour` steps only, one or two
 * per section, enough to say where each lives without turning a first login into
 * a lecture, and it does step into a detail view to show a section or two of it.
 * The header "?" is the *exhaustive* pass — every step of the section the reader
 * is in, including the whole of a detail view it opens, so asking for help on the
 * Agents list walks the list and then the builder, component by component. The
 * "?" set is a superset of the launch set per section.
 *
 * A step is gated on the permission that renders *its own target*, not merely on
 * being able to view the page: the create buttons are edit-gated, so a step
 * pointing at one carries the matching `*Edit` permission. That way a Viewer's
 * tour never stops on a control the server hid from them and left the spotlight
 * hunting an element that will never appear — it simply skips to the next step
 * they can act on. Copy lives in the catalog, never here, because a module
 * evaluated at import time cannot translate.
 */
export interface TourStep {
  id: string;
  page?: string;
  target?: string;
  /** A `[data-tour="…"]` to click before spotlighting — a tab that reveals the target. */
  activate?: string;
  permission?: Permission;
  /** Part of the curated first-run walkthrough. Omitted means "?"-only. */
  inTour?: boolean;
  /**
   * Skip this step when its target never mounts, rather than pinning the caption
   * to the middle of the screen with nothing highlighted. For a stop whose control
   * is data-conditional — the MCP catalog's filter, custom-add and connect only
   * render once the catalog has rows — so an empty catalog drops them from the walk
   * instead of stranding it. A required stop still shows centred, because a slow
   * page is not the same as an absent one.
   */
  optional?: boolean;
}

export const TOUR_STEPS: readonly TourStep[] = [
  { id: "welcome", inTour: true },

  { id: "dashboard-actions", page: ROUTES.DASHBOARD, target: "dashboard-actions", inTour: true },
  { id: "dashboard-filters", page: ROUTES.DASHBOARD, target: "dashboard-filters", inTour: true },
  // "?"-only: arranging the dashboard is detail the exhaustive walk covers, not a
  // first-run essential. Ungated — the layout is the reader's own, not org-scoped.
  { id: "dashboard-customize", page: ROUTES.DASHBOARD, target: "dashboard-customize" },

  { id: "chat-start", page: ROUTES.CHAT, target: "chat-start", inTour: true },
  { id: "chat-agent-picker", page: ROUTES.CHAT, target: "chat-agent-picker", inTour: true },
  { id: "chat-composer", page: ROUTES.CHAT, target: "chat-composer" },
  // Only there once an agent has planned something, so `optional` - an
  // organization whose agents carry no planning capability would otherwise wait
  // four seconds for a strip that never mounts.
  { id: "chat-plan", page: ROUTES.CHAT, target: "chat-plan", optional: true },
  { id: "chat-model-picker", page: ROUTES.CHAT, target: "chat-model-picker" },

  {
    id: "agents-new",
    page: ROUTES.AGENTS,
    target: "agents-new",
    permission: Perm.agentsEdit,
    inTour: true,
  },
  { id: "agents-filters", page: ROUTES.AGENTS, target: "agents-filters" },

  // The builder, entered from the Agents list. The engine opens an example agent
  // (the seeded "Getting Started", or the first one there is), switches to the
  // named tab, then spotlights the section. The launch pass takes one per tab —
  // enough for a short line on each section; the "?" adds the sub-cards (model,
  // MCP) the launch leaves out.
  {
    id: "agent-instructions",
    page: AGENT_BUILDER,
    target: "agent-instructions",
    activate: "agent-tab-build",
    permission: Perm.agentsView,
    inTour: true,
  },
  {
    id: "agent-model",
    page: AGENT_BUILDER,
    target: "agent-model",
    activate: "agent-tab-build",
    permission: Perm.agentsView,
  },
  {
    id: "agent-toolbox",
    page: AGENT_BUILDER,
    target: "agent-capabilities",
    activate: "agent-tab-toolbox",
    permission: Perm.agentsView,
    inTour: true,
  },
  {
    id: "agent-mcp",
    page: AGENT_BUILDER,
    // The card's header, not the card: the picker under it holds the whole server
    // catalog, so the card is taller than the screen and spotlighting it lit
    // everything — see the anchor's comment in the builder page.
    target: "agent-mcp-intro",
    activate: "agent-tab-mcp",
    permission: Perm.agentsView,
  },
  // What the agent is *given* - collections, skills - is picked inside the panel
  // of the capability that reads it, so these point at the row that opens that
  // panel rather than at the picker. The picker is two clicks in (tab, then row)
  // and `activate` clicks one thing; the row is also the bounded element, where
  // the panel runs past the bottom of the screen.
  {
    id: "agent-knowledge",
    page: AGENT_BUILDER,
    target: "capability-knowledge",
    activate: "agent-tab-toolbox",
    permission: Perm.agentsView,
    inTour: true,
  },
  {
    id: "agent-skills",
    page: AGENT_BUILDER,
    target: "capability-skills",
    activate: "agent-tab-toolbox",
    permission: Perm.agentsView,
    inTour: true,
  },
  {
    id: "agent-limits",
    page: AGENT_BUILDER,
    target: "agent-limits",
    activate: "agent-tab-limits",
    permission: Perm.agentsView,
    inTour: true,
  },
  {
    id: "agent-availability",
    page: AGENT_BUILDER,
    target: "agent-availability",
    activate: "agent-tab-availability",
    permission: Perm.agentsView,
    inTour: true,
  },
  {
    id: "agent-history",
    page: AGENT_BUILDER,
    target: "agent-history",
    activate: "agent-tab-history",
    permission: Perm.agentsView,
    inTour: true,
  },
  {
    id: "agent-publish",
    page: AGENT_BUILDER,
    target: "agent-publish",
    permission: Perm.agentsPublish,
    inTour: true,
  },

  {
    id: "skills-new",
    page: ROUTES.SKILLS,
    target: "skills-new",
    permission: Perm.skillsEdit,
    inTour: true,
  },
  { id: "skills-list", page: ROUTES.SKILLS, target: "skills-list", permission: Perm.skillsView },

  // Standing context — the files an organization injects into every agent's
  // prompt. Beside skills in the Build group, the same shape: a create button the
  // launch pass points at (edit-gated), and the list the "?" adds (view-gated).
  {
    id: "context-new",
    page: ROUTES.CONTEXT,
    target: "context-new",
    permission: Perm.contextEdit,
    inTour: true,
  },
  {
    id: "context-list",
    page: ROUTES.CONTEXT,
    target: "context-list",
    permission: Perm.contextView,
  },

  {
    id: "activity-overview",
    page: ROUTES.RUNS,
    target: "activity-overview",
    permission: Perm.runsView,
    inTour: true,
  },
  // The three tabs the "?" digs into, each switched to and described in turn —
  // approvals only where the caller may decide one, the same permission that
  // renders that tab.
  {
    id: "activity-approvals",
    page: ROUTES.RUNS,
    target: "activity-approvals",
    activate: "activity-tab-approvals",
    permission: Perm.approvalsDecide,
  },
  {
    id: "activity-runs",
    page: ROUTES.RUNS,
    target: "activity-runs",
    activate: "activity-tab-runs",
    permission: Perm.runsView,
  },
  {
    id: "activity-spend",
    page: ROUTES.RUNS,
    target: "activity-spend",
    activate: "activity-tab-spend",
    permission: Perm.runsView,
  },
  // Inside the run drawer, which opens only when somebody has focused a run - so
  // `optional`, like the MCP catalog's data-conditional controls. The walk skips
  // it with the drawer closed and describes it in place when a reader presses "?"
  // with a run open, which is exactly when the tab is worth explaining.
  {
    id: "run-detail-input",
    page: ROUTES.RUNS,
    target: "run-detail-input",
    permission: Perm.runsView,
    optional: true,
  },

  {
    id: "knowledge-new",
    page: ROUTES.RAG,
    target: "knowledge-new",
    permission: Perm.collectionsEdit,
    inTour: true,
  },
  {
    id: "knowledge-tabs",
    page: ROUTES.RAG,
    target: "knowledge-tabs",
    permission: Perm.collectionsView,
  },
  // The reusable connections — an S3 bucket, a drive, a repo configured once and
  // cloned into any collection. Both stops are gated on connections:manage, the
  // permission that renders the section and its "Add integration" button; without
  // it the section returns null and there is nothing to spotlight.
  {
    id: "knowledge-integrations",
    page: ROUTES.RAG,
    target: "knowledge-integrations",
    // Its own tab since #939, so the walk selects it first: a step pointing at a
    // control inside an unselected tab waits four seconds for an element that
    // never mounts.
    activate: "knowledge-tab-integrations",
    permission: Perm.connectionsManage,
  },
  // Optional: the "Add integration" button renders only once the connector catalog
  // has one to add (`reusable-integrations`), so on an empty or failed catalog its
  // target never mounts and the engine must skip the stop rather than pin a caption
  // on nothing — the same reason the MCP catalog controls carry it.
  {
    id: "knowledge-add-integration",
    page: ROUTES.RAG,
    target: "knowledge-add-integration",
    activate: "knowledge-tab-integrations",
    permission: Perm.connectionsManage,
    optional: true,
  },

  // The collection detail, entered from the Knowledge list. Three tabs since
  // #939, so each stop selects its own: the header and the stats strip are above
  // them and need no `activate`, and the three sections below do.
  { id: "kb-header", page: KB_DETAIL, target: "kb-header", permission: Perm.collectionsView },
  {
    id: "kb-documents",
    page: KB_DETAIL,
    target: "kb-documents",
    activate: "kb-tab-documents",
    permission: Perm.collectionsView,
    inTour: true,
  },
  {
    id: "kb-ingestion",
    page: KB_DETAIL,
    target: "kb-ingestion",
    activate: "kb-tab-ingestion",
    permission: Perm.collectionsView,
  },
  {
    id: "kb-sync",
    page: KB_DETAIL,
    target: "kb-sync",
    activate: "kb-tab-sync",
    permission: Perm.collectionsView,
  },

  { id: "orgs-new", page: ROUTES.ORGS, target: "orgs-new" },

  // The organization detail, entered from the workspaces list. Two routes, one
  // walk: the members page (profile, then the member list) and then a step
  // across into the roles matrix. Ungated — any member reaches both.
  { id: "org-profile", page: ORG_MEMBERS, target: "org-profile" },
  { id: "org-members", page: ORG_MEMBERS, target: "org-members" },
  { id: "org-roles", page: ORG_ROLES, target: "org-roles" },

  {
    id: "vault-new",
    page: ROUTES.VAULT,
    target: "vault-new",
    permission: Perm.secretsEdit,
    inTour: true,
  },
  { id: "vault-keys", page: ROUTES.VAULT, target: "vault-keys", permission: Perm.secretsView },

  {
    id: "mcp-catalog",
    page: ROUTES.MCP_SERVERS,
    target: "mcp-catalog",
    permission: Perm.agentsView,
    inTour: true,
  },
  // The catalog controls — filter, custom-add, connect — render only inside the
  // list, which the page swaps for an empty-state card when the catalog has no
  // rows. So they are optional: an empty catalog drops them rather than spotlighting
  // nothing. The catalog stop above stays, because its target moves onto the
  // empty-state card, so it always has something to point at.
  {
    id: "mcp-filter",
    page: ROUTES.MCP_SERVERS,
    target: "mcp-filter",
    permission: Perm.agentsView,
    optional: true,
  },
  {
    id: "mcp-add",
    page: ROUTES.MCP_SERVERS,
    target: "mcp-add",
    permission: Perm.connectionsManage,
    optional: true,
  },
  {
    id: "mcp-connect",
    page: ROUTES.MCP_SERVERS,
    target: "mcp-connect",
    permission: Perm.agentsView,
    optional: true,
  },

  // The chat platforms the organization is reachable on — beside MCP because it
  // is the same kind of thing, a connection the organization owns. The add button
  // is `channels:manage`, so the launch pass carries that; the list only needs the
  // view the sidebar gates the section on.
  {
    id: "channels-new",
    page: ROUTES.CHANNELS,
    target: "channels-new",
    permission: Perm.channelsManage,
    inTour: true,
  },
  {
    id: "channels-list",
    page: ROUTES.CHANNELS,
    target: "channels-list",
    permission: Perm.agentsView,
  },

  {
    id: "sandboxes-connections",
    page: ROUTES.SANDBOXES,
    target: "sandboxes-connections",
    permission: Perm.connectionsView,
  },

  // Routines — the org-wide home for everything an agent does on its own. Two
  // stops: what is already running, and the two ways to start one. The create
  // stop is gated on the run floor a trigger is created at, not on a role: a
  // Viewer holding one explicit run grant may create one, and an ungated step
  // would wait four seconds for a control a refusal never mounted.
  // "?"-only, like the workspaces stop: the launch pass is deliberately six steps
  // - welcome, the dashboard, the chat, finish - and a seventh about work nobody
  // has scheduled yet is a page a first login has no reason to visit.
  { id: "routines-list", page: ROUTES.ROUTINES, target: "routines-list" },
  {
    id: "routines-create",
    page: ROUTES.ROUTINES,
    target: "routines-create",
    permission: Perm.agentsRun,
  },

  { id: "workspaces-browser", page: ROUTES.WORKSPACES, target: "workspaces-browser" },
  // The detail a workspace opens onto — the file tree. "?"-only and shown in
  // place: the reader is already on one of their own workspaces, so the walk
  // spotlights the browser rather than opening an example there is none of.
  { id: "workspaces-detail", page: WORKSPACE_DETAIL, target: "workspace-files" },

  // Settings — the tabbed personal section. One "?" stop on the tabs, which live
  // in the shared layout, so it lands on whichever of the four pages the reader
  // opened help from. Ungated: everyone has their own settings.
  { id: "settings-tabs", page: SETTINGS_DETAIL, target: "settings-tabs" },

  { id: "finish", inTour: true },
];

/**
 * The pages of one "?" journey, in the order the walkthrough visits them.
 *
 * A section that leads from a list into a detail view — the Agents list into the
 * builder it opens — replays as one sequence, so asking for help on the list
 * walks the list and then steps into the builder. A page named in no flow is its
 * own journey.
 */
const SECTION_FLOWS: readonly (readonly string[])[] = [
  [ROUTES.AGENTS, AGENT_BUILDER],
  [ROUTES.RAG, KB_DETAIL],
  [ROUTES.ORGS, ORG_MEMBERS, ORG_ROLES],
];

/** The page identity a real pathname belongs to; detail routes collapse onto their pseudo-page. */
export function pageKey(path: string): string {
  if (path.startsWith(`${ROUTES.AGENTS}/`)) return AGENT_BUILDER;
  if (path.startsWith(`${ROUTES.RAG}/`)) return KB_DETAIL;
  if (path.startsWith(`${ROUTES.ORGS}/`)) return path.endsWith("/roles") ? ORG_ROLES : ORG_MEMBERS;
  if (path.startsWith(`${ROUTES.SETTINGS}/`)) return SETTINGS_DETAIL;
  if (path.startsWith(`${ROUTES.WORKSPACES}/`)) return WORKSPACE_DETAIL;
  return path;
}

/** The flow `pageId` belongs to, or a flow of just itself for a standalone page. */
function flowFor(pageId: string): readonly string[] {
  return SECTION_FLOWS.find((flow) => flow.includes(pageId)) ?? [pageId];
}

/**
 * The curated first-run walkthrough: the `inTour` steps, permission-filtered the
 * way the sidebar is, so a Viewer's tour is exactly the sections they can act on.
 */
export function visibleTourSteps(can: (permission: Permission) => boolean): readonly TourStep[] {
  return TOUR_STEPS.filter((step) => step.inTour && (!step.permission || can(step.permission)));
}

/**
 * Every highlight the "?" replays for the page at `path`, permission-filtered.
 *
 * It is the current page's own stops plus everything downstream of it in the same
 * flow: on the Agents list, the list stops and then the whole builder walk; on a
 * builder route, the builder walk alone, because the reader is already past the
 * list. Richer than the launch pass — it returns a section's `inTour` stops *and*
 * its "?"-only ones. The interstitials (welcome, finish) have no page and never
 * appear here.
 */
export function stepsForPage(
  path: string,
  can: (permission: Permission) => boolean,
): readonly TourStep[] {
  const current = pageKey(path);
  const flow = flowFor(current);
  const reachable = new Set(flow.slice(flow.indexOf(current)));
  return TOUR_STEPS.filter(
    (step) =>
      step.page !== undefined &&
      reachable.has(step.page) &&
      (!step.permission || can(step.permission)),
  );
}

/**
 * Whether this registry holds any stop for `path` at all — the question the "?"
 * button asks before offering itself.
 *
 * Deliberately blind to permissions, and that is the whole reason it is separate
 * from `stepsForPage`: the button lives in a header twenty surfaces render, and
 * making it wait on the permission query would drag react-query into every one of
 * them for an answer that only ever differs on a page which *has* stops. A page
 * with none in the registry — the deployment-admin section, the component
 * playground — can never grow them from a permission, so this is the whole of it;
 * a page whose stops a permission happens to filter to zero is caught later, by
 * `useOnboardingTour` closing a walk that opened empty.
 */
export function pageHasSteps(path: string): boolean {
  return stepsForPage(path, () => true).length > 0;
}
