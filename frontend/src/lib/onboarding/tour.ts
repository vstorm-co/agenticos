import { ROUTES } from "@/lib/constants";
import { Perm, type Permission } from "@/types/permissions";

/**
 * One stop on the guided tour.
 *
 * The engine (`components/onboarding`) navigates to `page`, waits for
 * `[data-tour="<target>"]` to mount, then spotlights it with a driver.js popover
 * carrying `onboarding.steps.<id>.title` and `.body`. A step with no `target` is
 * an interstitial shown as a centered popover (welcome, finish); one with no
 * `page` stays on whatever page the tour reached, so the closing card does not
 * yank the reader back to the dashboard.
 *
 * There are two readers of this list, and `inTour` is what tells them apart. The
 * first-run walkthrough is the *curated* pass — `inTour` steps only, one or two
 * per tab, enough to say where each section lives without turning a first login
 * into a lecture. The header "?" is the *exhaustive* pass — every step on the
 * page it is asked from, so a reader who wants the detail gets a component-by-
 * component tour of that one tab, unchained from the rest. The "?" set is a
 * superset of the launch set per page: a launch step also shows up under its
 * page's "?", a page-only step (`inTour` omitted) shows up only there.
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
    id: "knowledge-integrations",
    page: ROUTES.RAG,
    target: "knowledge-integrations",
    permission: Perm.collectionsView,
  },

  { id: "orgs-new", page: ROUTES.ORGS, target: "orgs-new" },

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
 * The curated first-run walkthrough: the `inTour` steps, permission-filtered the
 * way the sidebar is, so a Viewer's tour is exactly the tabs they can act on.
 */
export function visibleTourSteps(can: (permission: Permission) => boolean): readonly TourStep[] {
  return TOUR_STEPS.filter((step) => step.inTour && (!step.permission || can(step.permission)));
}

/**
 * Every highlight that lives on `path`, permission-filtered — what the "?"
 * button replays for one page, standalone and unchained from the rest of the
 * tour. Richer than the launch pass: it returns the page's `inTour` stops *and*
 * its "?"-only ones. The interstitials (welcome, finish) have no page and never
 * appear here.
 */
export function stepsForPage(
  path: string,
  can: (permission: Permission) => boolean,
): readonly TourStep[] {
  return TOUR_STEPS.filter(
    (step) => step.page === path && (!step.permission || can(step.permission)),
  );
}
