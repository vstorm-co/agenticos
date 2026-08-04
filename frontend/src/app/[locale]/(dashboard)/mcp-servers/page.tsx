"use client";

import { Plug } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { McpServerList, ServersCard } from "@/components/mcp/mcp-server-list";
import { Skeleton } from "@/components/ui";
import { useMcpServers, usePermissions } from "@/hooks";
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
 */
export default function McpServersPage() {
  const t = useTranslations("pages.mcp-servers");
  const { rows, isLoading } = useMcpServers();
  const { can } = usePermissions();

  return (
    <div className="space-y-6">
      <PageHeader title={t("mcpServers")} description={t("externalToolsYourAgents")} />

      {isLoading ? (
        // The same card frame the list draws, with card-shaped skeletons in the
        // same columns - a skeleton that draws a different shape is a layout
        // jump on every load.
        <ServersCard count={null}>
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
        </ServersCard>
      ) : rows.length === 0 ? (
        <ServersCard count={0}>
          {/* Inline rather than an `EmptyState`: that component draws its own
              bordered box, and inside a card it would frame one message twice. */}
          <div className="px-6 py-12 text-center">
            <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
              <Plug className="h-5 w-5" />
            </div>
            <p className="text-foreground mt-4 text-sm font-medium">{t("noServersConnect")}</p>
            <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">
              {t("catalogCompiledIntoBackend")}
            </p>
          </div>
        </ServersCard>
      ) : (
        <McpServerList canManageOrganization={can(Perm.connectionsManage)} />
      )}
    </div>
  );
}
