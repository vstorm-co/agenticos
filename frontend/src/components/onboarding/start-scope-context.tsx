"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { StartScope, StartScopeState } from "@/lib/onboarding-api";

export interface StartScopeJourney {
  scopes: readonly StartScopeState[];
  current: StartScope;
  select: (scope: StartScope) => void;
  pending: boolean;
  failed: boolean;
  continueReview?: () => void;
}
const Context = createContext<StartScopeJourney | null>(null);
export function StartScopeProvider({
  value,
  children,
}: {
  value: StartScopeJourney;
  children: ReactNode;
}) {
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export const useStartScopeJourney = () => useContext(Context);
