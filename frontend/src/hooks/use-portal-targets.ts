"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchPortalTargets } from "@/lib/portals-api";
import { qk } from "@/lib/query-keys";

/**
 * The targets (repositories, channels) a portal's preset can point at.
 *
 * Read from a connected account through its token, so it is held until the
 * portal, the connection and the agent are all known - the server authorizes
 * the read as `agents:run` on the agent the trigger is being built for, the
 * same per-resource floor as creating it. An empty answer is legitimate - a
 * portal that registers no webhooks, or an account whose targets cannot be
 * read - and the dialog falls back to a free-text target, so the caller reads
 * `targets` and `isError` together rather than treating emptiness as failure.
 */
export function usePortalTargets(
  portalKey: string | null,
  connectionId: string | null,
  agentId: string | null,
) {
  const enabled = portalKey !== null && connectionId !== null && agentId !== null;
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portals.targets(portalKey ?? "", connectionId ?? "", agentId ?? ""),
    queryFn: () =>
      fetchPortalTargets(portalKey as string, connectionId as string, agentId as string),
    enabled,
  });

  return { targets: data ?? [], isLoading: enabled && isLoading, isError };
}
