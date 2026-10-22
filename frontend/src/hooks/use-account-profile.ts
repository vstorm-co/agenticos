"use client";

import { useCallback } from "react";

import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";
import type { WorkingHours } from "@/types/auth";

/** What every agent is told about the person (#2301), as the account keeps it. */
export interface AgentContext {
  job_title?: string | null;
  about?: string | null;
  time_zone?: string | null;
  working_hours?: WorkingHours | null;
}

/**
 * Save what agents know about the signed-in person, and keep the session's copy
 * of the account in step with the answer. Throws what the request threw, for the
 * caller to say.
 */
export function useSaveAgentContext(): (changes: AgentContext) => Promise<User> {
  const setUser = useAuthStore((state) => state.setUser);
  return useCallback(
    async (changes: AgentContext) => {
      const updated = await apiClient.patch<User>("/users/me", changes);
      setUser(updated);
      return updated;
    },
    [setUser],
  );
}

/**
 * Leave the signed-in person out of the organization's nightly look, or let it
 * reach them again (#2301), keeping the session's copy of the account in step.
 */
export function useSaveProactiveOptOut(): (optOut: boolean) => Promise<User> {
  const setUser = useAuthStore((state) => state.setUser);
  return useCallback(
    async (optOut: boolean) => {
      const updated = await apiClient.patch<User>("/users/me", { proactive_opt_out: optOut });
      setUser(updated);
      return updated;
    },
    [setUser],
  );
}
