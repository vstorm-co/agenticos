/**
 * API client for the trigger-portals catalog.
 *
 * The same shape as `useMcpCatalog`'s fetch of `/agents/mcp-catalog`: a curated,
 * read-only list the deployment compiles in, reached through the same-origin
 * platform proxy. `fetchPortalTargets` is the one call that is not static - it
 * reads a connected account's repositories through its token, so it takes the
 * connection whose targets to enumerate.
 */

import { apiClient } from "./api-client";
import type {
  PortalCatalogEntry,
  PortalCatalogResponse,
  PortalTarget,
  PortalTargetResponse,
} from "@/types/portals";

export async function fetchPortalCatalog(): Promise<PortalCatalogEntry[]> {
  const data = await apiClient.get<PortalCatalogResponse>("/trigger-portals");
  return data.items;
}

export async function fetchPortalTargets(
  portalKey: string,
  connectionId: string,
): Promise<PortalTarget[]> {
  const data = await apiClient.get<PortalTargetResponse>(
    `/trigger-portals/${encodeURIComponent(portalKey)}/targets`,
    { params: { connection_id: connectionId } },
  );
  return data.items;
}
