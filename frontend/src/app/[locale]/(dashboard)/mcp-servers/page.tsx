"use client";

import { Plug } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { McpServerList } from "@/components/mcp/mcp-server-list";
import { ErrorState } from "@/components/states";
import { ListCard, ListCardEmpty, Skeleton } from "@/components/ui";
import { useMcpOAuthOutcome, useMcpServers, usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/**
 * MCP servers - the one page, where there used to be two.
 *
 * `/mcp-servers` listed the catalog and `/settings/integrations` listed a
 * person's connections, as if those were peers. They are not: there are three
 * layers, and only one of them is a page.
 *
 * - A **catalog entry** is a server that exists. Deployment-wide, curated by
 *   hand, read-only - nothing to manage, only something to connect to.
 * - A **connection** is a credential to one of them, owned by a person or by
 *   the organization. That is a property of a row, which is why it is now shown
 *   on one.
 * - A **binding** is which connection an agent may use. It lives in the agent's
 *   spec and is chosen in the Builder, not here.
 *
 * Presenting the first two as sibling destinations is what made "what is the
 * difference between MCP servers and Integrations?" a question nobody could
 * answer from the navigation. `/settings/integrations` now redirects here.
 *
 * It is also where a provider's OAuth redirect lands, which is why this page
 * announces that outcome rather than the connection dialog that started it: the
 * browser left the product entirely in between.
 */
export default function McpServersPage() {
  const t = useTranslations("pages.mcp-servers");
  const tMcp = useTranslations("mcp");
  const { rows, isLoading, error } = useMcpServers();
  const { can } = usePermissions();
  useMcpOAuthOutcome();

  return (
    <div className="space-y-6">
      <PageHeader title={t("mcpServers")} description={t("externalToolsYourAgents")} />

      {isLoading ? (
        // The same card frame the list draws, with card-shaped skeletons in the
        // same columns - a skeleton that draws a different shape is a layout
        // jump on every load.
        <ListCard title={tMcp("servers")} counted={null} contentClassName="p-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }, (_, tile) => (
              <div key={tile} className="border-border rounded-xl border p-4">
                <div className="flex items-start gap-2.5">
                  <Skeleton className="mt-0.5 h-6 w-6 shrink-0 rounded-md" />
                  <div className="min-w-0 flex-1 space-y-2">
                    <Skeleton className="h-4 w-24" />
                    <Skeleton className="h-3 w-full" />
                  </div>
                </div>
                <div className="border-border mt-4 border-t pt-3">
                  <Skeleton className="h-8 w-24" />
                </div>
              </div>
            ))}
          </div>
        </ListCard>
      ) : error ? (
        <ListCard title={tMcp("servers")} counted={tMcp("serverCount", { count: rows.length })}>
          <ErrorState />
        </ListCard>
      ) : rows.length === 0 ? (
        <ListCard title={tMcp("servers")} counted={tMcp("serverCount", { count: 0 })}>
          <ListCardEmpty
            icon={Plug}
            title={t("noServersConnect")}
            description={t("catalogCompiledIntoBackend")}
          />
        </ListCard>
      ) : (
        <McpServerList canManageOrganization={can(Perm.connectionsManage)} />
      )}
    </div>
  );
}
