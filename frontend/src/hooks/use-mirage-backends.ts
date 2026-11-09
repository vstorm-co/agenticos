"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { MirageBackendList } from "@/types/mirage";

/**
 * What the virtual terminal can mount on this deployment, with the form for each.
 *
 * Read from the deployment rather than listed here: which backends exist is the
 * installed Mirage's answer, and which of them can be mounted is the operator's.
 */
export function useMirageBackends() {
  return useQuery({
    queryKey: qk.agents.mirageBackends(),
    queryFn: () => apiClient.get<MirageBackendList>("/agents/capabilities/mirage/backends"),
    // Fixed until the deployment is redeployed.
    staleTime: Infinity,
  });
}
