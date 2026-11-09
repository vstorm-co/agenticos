"use client";

import { AuthGuard } from "@/components/layout/auth-guard";
import { ActiveOrgGuard } from "@/components/layout/active-org-guard";
import { AccountLocale } from "@/components/layout/account-locale";
import { StartEntry } from "./start-entry";

/** Kept as the route boundary for historical /onboarding links. */
export function OnboardingPlaceholder() {
  return (
    <AuthGuard>
      <ActiveOrgGuard />
      <AccountLocale />
      <main className="bg-background text-foreground min-h-dvh">
        <div
          aria-hidden="true"
          className="hidden h-12 shrink-0 [body:has([data-invitation-entry])_&]:block"
        />
        <StartEntry />
      </main>
    </AuthGuard>
  );
}
