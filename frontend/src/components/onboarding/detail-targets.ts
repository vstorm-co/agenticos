"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { AGENT_BUILDER, KB_DETAIL } from "@/lib/onboarding/tour";
import { qk } from "@/lib/query-keys";
import type { AgentList } from "@/types/agents";
import type { KnowledgeBaseList } from "@/types/knowledge-base";

/** Where a detail pseudo-page resolves to, and whether we are still finding out. */
export interface ResolvedDetail {
  /** True while the list this route is picked from is still loading. */
  pending: boolean;
  /** The concrete route to open, or null when there is nothing to open. */
  href: string | null;
}

/**
 * For each detail pseudo-page a tour step can name, the concrete route the engine
 * pushes to reach an example of it.
 *
 * A detail view has no route of its own, so the walkthrough opens a real one: the
 * seeded demo where there is one, otherwise the first row. The list is fetched
 * only while the tour is open, and a null `href` (an empty list) tells the engine
 * to skip that section's steps rather than spotlight a route that would 404. The
 * "?" replayed *from* a detail route never consults this — the reader is already
 * on the row they mean, and the engine keeps them there.
 */
export function useDetailTargets(enabled: boolean): Record<string, ResolvedDetail> {
  const agents = useQuery({
    queryKey: qk.agents.list(false),
    queryFn: () => apiClient.get<AgentList>("/agents"),
    enabled,
  });
  const agentId =
    agents.data?.items.find((agent) => agent.slug === "getting-started")?.id ??
    agents.data?.items[0]?.id ??
    null;

  const kbs = useQuery({
    queryKey: qk.kb.list(),
    queryFn: () => apiClient.get<KnowledgeBaseList>("/kb"),
    enabled,
  });
  const kbId = kbs.data?.items.find((kb) => kb.is_default)?.id ?? kbs.data?.items[0]?.id ?? null;

  return useMemo(
    () => ({
      [AGENT_BUILDER]: {
        pending: enabled && agents.isPending,
        href: agentId ? ROUTES.AGENT_DETAIL(agentId) : null,
      },
      [KB_DETAIL]: {
        pending: enabled && kbs.isPending,
        href: kbId ? ROUTES.RAG_DETAIL(kbId) : null,
      },
    }),
    [enabled, agents.isPending, agentId, kbs.isPending, kbId],
  );
}
