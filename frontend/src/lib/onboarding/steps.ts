import {
  Activity,
  BookOpen,
  Bot,
  Database,
  KeyRound,
  LayoutDashboard,
  MessageSquare,
  Rocket,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { Perm, type Permission } from "@/types/permissions";

export interface OnboardingStep {
  /** Stable id. The copy lives at catalog keys `onboarding.steps.<id>.title` and `.body`. */
  id: string;
  icon: LucideIcon;
  /** Shown only to a caller who holds this; omitted means shown to everyone. */
  permission?: Permission;
}

/**
 * The first-run walkthrough, one step per destination it teaches.
 *
 * Each step gated exactly as the primary navigation gates the same destination
 * (`components/layout/app-sidebar.tsx`), so the tour walks a caller through the
 * pages their sidebar actually shows and never stops on a control they would be
 * refused: a Viewer holds `agents:view` but neither `runs:view` nor
 * `secrets:view`, so their tour skips Activity and the Vault. `welcome` and
 * `finish` carry no permission, so the list is never empty.
 *
 * The table holds ids and icons, never copy: a module evaluated at import time
 * cannot call a translator, so the component reads `steps.<id>.title` and
 * `.body` at the point of use.
 */
export const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  { id: "welcome", icon: Sparkles },
  { id: "dashboard", icon: LayoutDashboard },
  { id: "chat", icon: MessageSquare },
  { id: "agents", icon: Bot, permission: Perm.agentsView },
  { id: "skills", icon: BookOpen, permission: Perm.skillsView },
  { id: "activity", icon: Activity, permission: Perm.runsView },
  { id: "knowledge", icon: Database, permission: Perm.collectionsView },
  { id: "vault", icon: KeyRound, permission: Perm.secretsView },
  { id: "finish", icon: Rocket },
];

/** The steps a caller actually sees, filtered by permission the way the nav is. */
export function visibleOnboardingSteps(
  can: (permission: Permission) => boolean,
): readonly OnboardingStep[] {
  return ONBOARDING_STEPS.filter((step) => !step.permission || can(step.permission));
}
