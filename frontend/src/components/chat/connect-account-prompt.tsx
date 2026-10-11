"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Plug } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ConnectOwnServerDialog } from "@/components/agents/connect-server-dialog";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { Button } from "@/components/ui";
import { useMcpConnections } from "@/hooks/use-mcp-connections";
import { useMcpCatalog } from "@/hooks/use-mcp-servers";
import { ROUTES } from "@/lib/constants";
import { getPathname } from "@/lib/locale-navigation";
import { ownAccountStatus } from "@/lib/mcp-servers";
import type { ConnectionRequest } from "@/types";
import type { McpCatalogEntry } from "@/types/mcp";

/**
 * A run paused on `connect_account`: the agent reached for one of this person's
 * own services, and waits while they connect it.
 *
 * Everything here keeps this tab where it is, because the run is held by this
 * tab's socket and navigating away would release it as a skip. An OAuth consent
 * opens in a new tab (the dialog does that when given no `returnTo`), and so does
 * the servers page, for an account that needs marking as default or authorizing
 * again.
 *
 * The run carries on by itself once the connections list *changes* to say the
 * service is connected - the dialog writes that list's cache, and a consent
 * finished in the other tab is read when this one regains focus. A change, not
 * the value: a token that expired still reads as authorized in the list, so a
 * list that already said "connected" when the card went up is no evidence the
 * gap was fixed. "Continue" is for everything the list cannot see; the server
 * reads the connection again either way.
 */
export function ConnectAccountPrompt({
  request,
  disabled,
  onRespond,
}: {
  request: ConnectionRequest;
  disabled: boolean;
  onRespond: (connected: boolean) => void;
}) {
  const t = useTranslations("chat.connectAccount");
  const locale = useLocale();
  const { servers } = useMcpCatalog();
  const { connections, isLoading, isFetching } = useMcpConnections();
  const [connecting, setConnecting] = useState<McpCatalogEntry | null>(null);
  const entry = servers.find((one) => one.key === request.catalog_key) ?? null;
  const status = ownAccountStatus(request.catalog_key, connections);
  // What the list said once it had loaded, which is what a fix is a change from.
  // After the refresh a mount starts too: a cached list is loaded but old, and a
  // baseline read from it would count that refresh as the fix.
  const [before, setBefore] = useState<string | null>(null);
  if (!isLoading && !isFetching && before === null) setBefore(status);
  const repaired = before !== null && before !== "connected" && status === "connected";

  useEffect(() => {
    if (repaired && !disabled) onRespond(true);
  }, [repaired, disabled, onRespond]);

  return (
    <div role="status" className="border-border bg-card rounded-2xl border p-3 shadow-sm">
      <div className="flex items-center gap-3">
        <McpServerIcon icon={entry?.icon ?? null} name={request.name} />
        <span className="min-w-0 flex-1">
          <span className="block text-xs font-medium">{t("title", { name: request.name })}</span>
          <span className="text-muted-foreground block text-xs leading-relaxed">
            {t(`gap.${request.gap}`, { name: request.name })}
          </span>
        </span>
      </div>
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={disabled}
          onClick={() => onRespond(false)}
        >
          {t("skip")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() => onRespond(true)}
        >
          {t("continue")}
        </Button>
        {request.gap === "not_connected" && entry !== null ? (
          <Button type="button" size="sm" disabled={disabled} onClick={() => setConnecting(entry)}>
            <Plug className="mr-1 h-3.5 w-3.5" />
            {t("connect")}
          </Button>
        ) : (
          <Button size="sm" asChild>
            <a
              href={getPathname({ href: ROUTES.MCP_SERVERS, locale })}
              target="_blank"
              rel="noopener noreferrer"
            >
              <ExternalLink className="mr-1 h-3.5 w-3.5" />
              {t("openServers")}
            </a>
          </Button>
        )}
      </div>
      <ConnectOwnServerDialog entry={connecting} onClose={() => setConnecting(null)} keepThisTab />
    </div>
  );
}
