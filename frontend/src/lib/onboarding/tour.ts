import { ROUTES } from "@/lib/constants";
import { Perm, type Permission } from "@/types/permissions";

/**
 * One stop on the guided tour.
 *
 * The engine (`components/onboarding`) navigates to `page`, waits for
 * `[data-tour="<target>"]` to mount, then spotlights it while a docked panel
 * shows `onboarding.steps.<id>.title` and `.body`. A step with no `target` is an
 * interstitial — panel, no spotlight — and one with no `page` stays on whatever
 * page the tour reached (the closing step, so it does not yank the reader back to
 * the dashboard). Gated exactly as the primary nav gates the same destination
 * (`app-sidebar.tsx`), so a Viewer's tour is the pages their sidebar shows and
 * never stops on a control they would be refused. The copy lives in the catalog,
 * never here, because a module evaluated at import time cannot translate.
 */
export interface TourStep {
  id: string;
  page?: string;
  target?: string;
  permission?: Permission;
}

export const TOUR_STEPS: readonly TourStep[] = [
  { id: "welcome", page: ROUTES.DASHBOARD },
  { id: "dashboard", page: ROUTES.DASHBOARD, target: "dashboard-overview" },
  { id: "chat", page: ROUTES.CHAT, target: "chat-start" },
  { id: "agents", page: ROUTES.AGENTS, target: "agents-new", permission: Perm.agentsView },
  { id: "skills", page: ROUTES.SKILLS, target: "skills-new", permission: Perm.skillsView },
  { id: "activity", page: ROUTES.RUNS, target: "activity-overview", permission: Perm.runsView },
  { id: "knowledge", page: ROUTES.RAG, target: "knowledge-new", permission: Perm.collectionsView },
  { id: "vault", page: ROUTES.VAULT, target: "vault-new", permission: Perm.secretsView },
  { id: "finish" },
];

/** The steps a caller sees, filtered by permission the way the nav is. */
export function visibleTourSteps(can: (permission: Permission) => boolean): readonly TourStep[] {
  return TOUR_STEPS.filter((step) => !step.permission || can(step.permission));
}
