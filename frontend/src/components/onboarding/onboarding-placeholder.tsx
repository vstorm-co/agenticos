"use client";

import { AuthGuard } from "@/components/layout/auth-guard";
import { ActiveOrgGuard } from "@/components/layout/active-org-guard";
import { AccountAppearance } from "@/components/layout/account-appearance";
import { AccountLocale } from "@/components/layout/account-locale";
import { StartExperience } from "./start-experience";
import { StartEntry } from "./start-entry";

/** Kept as the route boundary for historical /onboarding links. */
export function OnboardingPlaceholder() {
  return (
    <AuthGuard>
      <ActiveOrgGuard />
      <AccountLocale />
      <AccountAppearance />
      <main className="bg-background text-foreground min-h-dvh">
        <StartExperience>
          <StartEntry />
        </StartExperience>
      </main>
    </AuthGuard>
  );
}
