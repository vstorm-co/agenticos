"use client";

import { Plug } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { McpServerList } from "@/components/mcp/mcp-server-list";
import { EmptyState, LoadingState } from "@/components/states";
import { useMcpServers, usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";

/**
 * MCP servers — the one page, where there used to be two.
 *
 * `/mcp-servers` listed the catalog and `/settings/integrations` listed a
 * person's connections, as if those were peers. They are not: there are three
 * layers, and only one of them is a page.
 *
 * - A **catalog entry** is a server that exists. Deployment-wide, curated by
 *   hand, read-only — nothing to manage, only something to connect to.
 * - A **connection** is a credential to one of them, owned by a person or by
 *   the organization. That is a property of a row, which is why it is now shown
 *   on one.
 * - A **binding** is which connection an agent may use. It lives in the agent's
 *   spec and is chosen in the Builder, not here.
 *
 * Presenting the first two as sibling destinations is what made "what is the
 * difference between MCP servers and Integrations?" a question nobody could
 * answer from the navigation. `/settings/integrations` now redirects here.
 */
export default function McpServersPage() {
  const { rows, isLoading } = useMcpServers();
  const { can } = usePermissions();

  return (
    <div className="space-y-6">
      <PageHeader
        title="MCP servers"
        description="External tools your agents and your assistant can call. Connecting a server for the organization makes it available to every agent; connecting it for yourself keeps it to your own chat. A published agent can only use the organization's, because what an agent reaches must not depend on who is running it."
      />

      {/* `McpServerList` lays the catalog out three-up, four on a wide window,
          so the skeleton takes those columns rather than the variant's default. */}
      {isLoading ? (
        <LoadingState variant="skeleton-cards" rows={8} className="lg:grid-cols-3 xl:grid-cols-4" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Plug}
          title="No servers to connect"
          description="The catalog is compiled into the backend, and nobody has added a server of their own. An empty list here means this deployment ships none."
        />
      ) : (
        <McpServerList canManageOrganization={can(Perm.connectionsManage)} />
      )}
    </div>
  );
}
