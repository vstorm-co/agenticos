"use client";

import { useTranslations } from "next-intl";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { useMcpCatalog } from "@/hooks";
import { cn } from "@/lib/utils";

/**
 * Which account a watch reads, as a person recognises it: the server's mark and
 * its catalog name, with the connection's own name beside it only when that says
 * something more - "Linear", not "linear"; "Notion (Work)" for a second account.
 */
export function useAccountName() {
  const t = useTranslations("watches");
  const { servers } = useMcpCatalog();
  return (server: string | null, connectionName: string) => {
    const entry = servers.find((each) => each.key === server);
    const name =
      !entry || entry.name.toLowerCase() === connectionName.toLowerCase()
        ? (entry?.name ?? connectionName)
        : t("accountNamed", { server: entry.name, account: connectionName });
    return { entry, name };
  };
}

export function WatchAccount({
  server,
  connectionName,
  className,
}: {
  server: string | null;
  connectionName: string;
  className?: string;
}) {
  const { entry, name } = useAccountName()(server, connectionName);
  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)}>
      <McpServerIcon
        icon={entry?.icon}
        name={entry?.name ?? connectionName}
        url={entry?.url}
        className="h-4 w-4 shrink-0"
      />
      <span className="truncate">{name}</span>
    </span>
  );
}
