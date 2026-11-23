"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { safeStartLocation, startLocationKey } from "@/lib/onboarding/start-location";

export const ONBOARDING_LOCATION_KEY = "onboarding-location";
interface OnboardingLocationState {
  startLocations: Record<string, string>;
  rememberStartLocation: (userId: string, organizationId: string, href: string) => void;
  clearStartLocation: (userId: string, organizationId: string) => void;
}

/** Untrusted persisted UI data may restore navigation only, never other onboarding state. */
function restoredLocations(persisted: unknown): Record<string, string> {
  const locations: Record<string, string> = {};
  if (!persisted || typeof persisted !== "object" || !("startLocations" in persisted))
    return locations;
  const stored = persisted.startLocations;
  if (!stored || typeof stored !== "object" || Array.isArray(stored)) return locations;
  for (const [key, href] of Object.entries(stored)) {
    if (typeof href !== "string") continue;
    let scope: unknown;
    try {
      scope = JSON.parse(key);
    } catch {
      continue;
    }
    if (!Array.isArray(scope) || scope.length !== 2) continue;
    const [userId, orgId]: unknown[] = scope;
    if (typeof userId !== "string" || !userId || typeof orgId !== "string" || !orgId) continue;
    const safe = safeStartLocation(href, orgId);
    if (safe) locations[startLocationKey(userId, orgId)] = safe;
  }
  return locations;
}

/** A return address for this browser; completion and snoozing remain server-owned. */
export const useOnboardingLocationStore = create<OnboardingLocationState>()(
  persist(
    (set) => ({
      startLocations: {},
      rememberStartLocation: (userId, organizationId, href) => {
        const safe = safeStartLocation(href, organizationId);
        if (!userId || !organizationId || !safe) return;
        const key = startLocationKey(userId, organizationId);
        set((state) =>
          state.startLocations[key] === safe
            ? state
            : { startLocations: { ...state.startLocations, [key]: safe } },
        );
      },
      clearStartLocation: (userId, organizationId) =>
        set((state) => {
          const key = startLocationKey(userId, organizationId);
          if (!(key in state.startLocations)) return state;
          const startLocations = { ...state.startLocations };
          delete startLocations[key];
          return { startLocations };
        }),
    }),
    {
      name: ONBOARDING_LOCATION_KEY,
      partialize: (state) => ({ startLocations: state.startLocations }),
      merge: (persisted, current) => ({ ...current, startLocations: restoredLocations(persisted) }),
    },
  ),
);
