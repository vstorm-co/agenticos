"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { AgentList } from "@/types/agents";

/** The server's page-size ceiling, so the sweep takes as few requests as it can. */
const PAGE_SIZE = 100;

/**
 * Whether the caller may create a trigger on *any* agent - the floor for the
 * org-wide create controls that are not tied to one agent, the chat sidebar's
 * "New" menu and the Routines page's "New schedule" - with the answer's own
 * loading state, for a caller that must wait for it rather than read the
 * conservative false (the onboarding snapshot, which would otherwise freeze
 * "no runnable agent" from the unanswered first frame).
 *
 * The floor is a per-agent signal, not the role-level `agents:run`: a Viewer
 * granted run on a single agent may create a trigger there, so the control has
 * to show for them even though their role reaches no agent. And it has to look
 * past the first page - that one runnable agent can sit anywhere in the list,
 * so the sweep pages through `/agents` until it finds one or runs out, stopping
 * at the first hit (for most callers, the first page).
 */
export function useCanCreateTriggerQuery(): {
  canCreate: boolean;
  isLoading: boolean;
  isFetching: boolean;
} {
  const { data, isLoading, isFetching } = useQuery({
    queryKey: qk.agents.anyRunnable(),
    queryFn: async () => {
      for (let skip = 0; ; skip += PAGE_SIZE) {
        const page = await apiClient.get<AgentList>("/agents", {
          params: { skip: String(skip), limit: String(PAGE_SIZE) },
        });
        if (page.items.some((agent) => agent.can_run)) return true;
        // `items.length` guards a short or empty page the `total` disagrees
        // with - an agent deleted mid-sweep must end the loop, not spin it.
        if (page.items.length === 0 || skip + page.items.length >= page.total) return false;
      }
    },
  });
  return { canCreate: data ?? false, isLoading, isFetching };
}

/**
 * The same answer as a bare boolean, false while it loads - the same
 * conservatism `usePermissions` applies, so a control is revealed once the data
 * says it may be rather than flashed and withdrawn.
 */
export function useCanCreateTrigger(): boolean {
  return useCanCreateTriggerQuery().canCreate;
}
