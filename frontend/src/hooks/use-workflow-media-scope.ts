"use client";

import { useAuthStore, useOrgStore } from "@/stores";

function authKey(state: ReturnType<typeof useAuthStore.getState>): string {
  return JSON.stringify([
    state.sessionOwnerId,
    state.user?.id ?? null,
    state.isAuthenticated,
    state.impersonationRevoked,
  ]);
}

function orgKey(state: ReturnType<typeof useOrgStore.getState>): string {
  return JSON.stringify([state.activeOrgId, state.refusedOrgIds.includes(state.activeOrgId ?? "")]);
}

/** A private media read belongs to this browser identity and selected organization. */
export function useWorkflowMediaScope(): string {
  const auth = useAuthStore(authKey);
  const organization = useOrgStore(orgKey);
  return JSON.stringify([auth, organization]);
}

export function isWorkflowMediaScopeCurrent(scope: string): boolean {
  const auth = useAuthStore.getState();
  const org = useOrgStore.getState();
  return (
    JSON.stringify([authKey(auth), orgKey(org)]) === scope &&
    auth.isAuthenticated &&
    !auth.impersonationRevoked &&
    auth.user !== null &&
    org.activeOrgId !== null &&
    !org.refusedOrgIds.includes(org.activeOrgId)
  );
}
