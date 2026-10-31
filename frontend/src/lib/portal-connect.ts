import {
  startGithubOrgOAuth,
  startMcpOAuth,
  startPolledPortalOAuth,
} from "@/lib/mcp-connections-api";
import type { PortalCatalogEntry } from "@/types/portals";

/** What starting a portal's connection needs to know about it - `PortalWithState`. */
export interface PortalToConnect {
  portal: Pick<PortalCatalogEntry, "key" | "name" | "delivery" | "event_source">;
  serverName: string | null;
  serverUrl: string | null;
}

/**
 * Where the browser goes to connect a portal's account for the organization.
 *
 * Three flows, because three kinds of provider. GitHub cannot be discovered
 * like a generic MCP server, so its consent URL is built from the organization's
 * own OAuth App secret keyed by the portal. A *polled* portal registers nothing
 * and only needs a refreshable token, on the deployment's own client. Everything
 * else follows discovery-and-registration.
 */
export async function portalConnectUrl(item: PortalToConnect): Promise<string> {
  const { authorization_url } =
    item.portal.delivery === "polling"
      ? await startPolledPortalOAuth(item.portal.key)
      : item.portal.event_source === "github"
        ? await startGithubOrgOAuth(item.portal.key)
        : await startMcpOAuth(
            { name: item.serverName ?? item.portal.name, url: item.serverUrl ?? "" },
            "organization",
          );
  return authorization_url;
}
