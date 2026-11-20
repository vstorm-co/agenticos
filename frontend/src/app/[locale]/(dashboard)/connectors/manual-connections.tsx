"use client";

import { Plug } from "lucide-react";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import { McpServerList } from "@/components/mcp/mcp-server-list";
import { ErrorState } from "@/components/states";
import { ListCard, ListCardEmpty, Skeleton } from "@/components/ui";
import { useMcpServers, usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";

/**
 * The MCP tab of Connections: the catalog of servers an agent can use, and a
 * person's or the organization's connections to them.
 *
 * Three layers, only one of them shown as a list: a **catalog entry** is a
 * server that exists (read-only, compiled into the deployment); a
 * **connection** is a credential to one, owned by a person or the
 * organization, shown on its row; a **binding** is which connection an agent
 * may use, chosen in the Builder.
 *
 * The parent page handles legacy OAuth outcomes, including returns to this tab.
 */
export function ManualConnections() {
  const t = useTranslations("pages.mcp-servers");
  const tMcp = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const { rows, isLoading, error } = useMcpServers();
  const { can } = usePermissions();

  if (isLoading) {
    // The same card frame the list draws, with card-shaped skeletons in the
    // same columns - a skeleton that draws a different shape is a layout
    // jump on every load.
    return (
      <ListCard fill namedByPage title={tMcp("servers")} counted={null} contentClassName="p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
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
    );
  }

  if (error) {
    // `counted` stays null while refused: the count was never answered,
    // and "0 servers" over a failure would state it as fact.
    return (
      <ListCard fill namedByPage title={tMcp("servers")} counted={null}>
        <ErrorState description={getErrorMessage(error, tErrors)} />
      </ListCard>
    );
  }

  if (rows.length === 0) {
    return (
      <ListCard
        fill
        namedByPage
        headerTour="mcp-catalog"
        title={tMcp("servers")}
        counted={tMcp("serverCount", { count: 0 })}
      >
        <ListCardEmpty
          icon={Plug}
          title={t("noServersConnect")}
          description={t("catalogCompiledIntoBackend")}
        />
      </ListCard>
    );
  }

  return (
    <McpServerList canManageOrganization={can(Perm.mcpManage)} retryOrganizationOnMount={false} />
  );
}
