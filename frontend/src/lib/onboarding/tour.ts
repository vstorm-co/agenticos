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
}

export const TOUR_STEPS: readonly TourStep[] = [
  { id: "welcome" },
  { id: "dashboard-actions", page: ROUTES.DASHBOARD, target: "dashboard-actions" },
  { id: "dashboard-filters", page: ROUTES.DASHBOARD, target: "dashboard-filters" },
  { id: "chat-start", page: ROUTES.CHAT, target: "chat-start" },
  { id: "agents-new", page: ROUTES.AGENTS, target: "agents-new", permission: Perm.agentsEdit },
  { id: "skills-new", page: ROUTES.SKILLS, target: "skills-new", permission: Perm.skillsEdit },
  {
    id: "activity-overview",
    page: ROUTES.RUNS,
    target: "activity-overview",
    permission: Perm.runsView,
  },
  {
    id: "knowledge-new",
    page: ROUTES.RAG,
    target: "knowledge-new",
    permission: Perm.collectionsEdit,
  },
  { id: "vault-new", page: ROUTES.VAULT, target: "vault-new", permission: Perm.secretsEdit },
  { id: "finish" },
];

/** The steps a caller sees, filtered by permission the way the pages are. */
export function visibleTourSteps(can: (permission: Permission) => boolean): readonly TourStep[] {
  return TOUR_STEPS.filter((step) => !step.permission || can(step.permission));
}

/**
 * The highlight steps that live on `path`, permission-filtered — what the "?"
 * button replays for one page, standalone and unchained from the rest of the
 * tour. The interstitials (welcome, finish) have no page and never appear here.
 */
export function stepsForPage(
  path: string,
  can: (permission: Permission) => boolean,
): readonly TourStep[] {
  return visibleTourSteps(can).filter((step) => step.page === path);
}
