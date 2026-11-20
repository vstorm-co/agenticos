"use client";

import { AuthGuard } from "@/components/layout/auth-guard";
import { TeamBuilder } from "./team-builder";

/** Guided onboarding: questions to recommend, assemble and deploy a custom team of agents. */
export function OnboardingSetup() {
  return (
    <AuthGuard>
      <TeamBuilder />
    </AuthGuard>
  );
}
