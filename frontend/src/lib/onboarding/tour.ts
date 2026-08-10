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
}

export const TOUR_STEPS: readonly TourStep[] = [
  { id: "welcome", inTour: true },

  { id: "dashboard-actions", page: ROUTES.DASHBOARD, target: "dashboard-actions", inTour: true },
  { id: "dashboard-filters", page: ROUTES.DASHBOARD, target: "dashboard-filters", inTour: true },

  { id: "chat-start", page: ROUTES.CHAT, target: "chat-start", inTour: true },
  { id: "chat-agent-picker", page: ROUTES.CHAT, target: "chat-agent-picker", inTour: true },
  { id: "chat-composer", page: ROUTES.CHAT, target: "chat-composer" },
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
  // (the seeded "Getting Started", or the first one there is), clicks the named
  // tab, then spotlights the section. The launch pass takes three of these —
  // instructions, tools, publish; the "?" walks every tab.
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
    target: "agent-mcp",
    activate: "agent-tab-toolbox",
    permission: Perm.agentsView,
  },
  {
    id: "agent-knowledge",
    page: AGENT_BUILDER,
    target: "agent-collections",
    activate: "agent-tab-knowledge",
    permission: Perm.agentsView,
  },
  {
    id: "agent-skills",
    page: AGENT_BUILDER,
    target: "agent-skills",
    activate: "agent-tab-skills",
    permission: Perm.agentsView,
  },
  {
    id: "agent-limits",
    page: AGENT_BUILDER,
    target: "agent-limits",
    activate: "agent-tab-limits",
    permission: Perm.agentsView,
  },
  {
    id: "agent-availability",
    page: AGENT_BUILDER,
    target: "agent-availability",
    activate: "agent-tab-availability",
    permission: Perm.agentsView,
  },
  {
    id: "agent-history",
    page: AGENT_BUILDER,
    target: "agent-history",
    activate: "agent-tab-history",
    permission: Perm.agentsView,
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
  { id: "skills-library", page: ROUTES.SKILLS, target: "skills-library" },

  {
    id: "activity-overview",
    page: ROUTES.RUNS,
    target: "activity-overview",
    permission: Perm.runsView,
    inTour: true,
  },
  { id: "activity-tabs", page: ROUTES.RUNS, target: "activity-tabs", permission: Perm.runsView },

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
  {
    id: "knowledge-integrations",
    page: ROUTES.RAG,
    target: "knowledge-integrations",
    permission: Perm.collectionsView,
  },

  // The collection detail, entered from the Knowledge list. Stacked sections
  // rather than tabs, so no `activate` — driver scrolls each into view.
  { id: "kb-header", page: KB_DETAIL, target: "kb-header", permission: Perm.collectionsView },
  {
    id: "kb-documents",
    page: KB_DETAIL,
    target: "kb-documents",
    permission: Perm.collectionsView,
    inTour: true,
  },
  { id: "kb-ingestion", page: KB_DETAIL, target: "kb-ingestion", permission: Perm.collectionsView },
  { id: "kb-sync", page: KB_DETAIL, target: "kb-sync", permission: Perm.collectionsView },

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

  {
    id: "mcp-catalog",
    page: ROUTES.MCP_SERVERS,
    target: "mcp-catalog",
    permission: Perm.agentsView,
    inTour: true,
  },
  { id: "mcp-filter", page: ROUTES.MCP_SERVERS, target: "mcp-filter", permission: Perm.agentsView },
  {
    id: "mcp-add",
    page: ROUTES.MCP_SERVERS,
    target: "mcp-add",
    permission: Perm.connectionsManage,
  },
  {
    id: "mcp-connect",
    page: ROUTES.MCP_SERVERS,
    target: "mcp-connect",
    permission: Perm.agentsView,
  },

  {
    id: "sandboxes-connections",
    page: ROUTES.SANDBOXES,
    target: "sandboxes-connections",
    permission: Perm.connectionsView,
  },

  { id: "workspaces-browser", page: ROUTES.WORKSPACES, target: "workspaces-browser" },

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
