"use client";

import { useState } from "react";
import { Check, ExternalLink, Plug } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConnectOwnServerDialog } from "@/components/agents/connect-server-dialog";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { Button } from "@/components/ui";
import { useAgents, useAgentVersion } from "@/hooks/use-agents";
import { useMcpConnections } from "@/hooks/use-mcp-connections";
import { useMcpCatalog } from "@/hooks/use-mcp-servers";
import { ownAccountStatus } from "@/lib/mcp-servers";
import { ROUTES } from "@/lib/constants";
import { useAgentSelectionStore } from "@/stores";
import type { PersonalMcpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";

/**
 * Which of the selected agent's services speak through *your* accounts, and
 * whether each is ready.
 *
 * The agent's bindings to each person's own account, read off the version that
 * runs, against the connections this person holds: connected, not connected,
 * several with none marked default, or one that no longer authorizes. Here, in
 * the chat's own settings, so somebody new finds out before their first
 * question rather than from the agent's refusal after it. Nothing to show for an
 * agent whose bindings are all the organization's, so an agent like that adds
 * no section.
 */
export function YourConnections() {
  const t = useTranslations("chat.personalServices");
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents } = useAgents({ includeArchived: true });
  const agent = agents.find((one) => one.id === selectedAgentId) ?? null;
  // The published version, not the draft: the draft is what somebody is editing,
  // and the chat runs what was published.
  const { version } = useAgentVersion(agent?.id ?? null, agent?.current_version_id ?? null);
  const { connections } = useMcpConnections();
  const { servers } = useMcpCatalog();
  const [connecting, setConnecting] = useState<McpCatalogEntry | null>(null);

  const personal = (version?.spec.mcp_servers ?? []).filter(
    (ref): ref is PersonalMcpServerRef => ref.account === "personal",
  );
  if (personal.length === 0) return null;

  return (
    <div className="border-foreground/10 mt-4 border-t pt-4" data-tour="chat-your-connections">
      <p className="text-foreground/55 mb-3 text-xs leading-relaxed">{t("yourAccounts")}</p>
      <ul className="space-y-1">
        {personal.map((ref) => {
          const entry = servers.find((one) => one.key === ref.catalog_key) ?? null;
          const name = entry?.name ?? ref.catalog_key;
          const status = ownAccountStatus(ref.catalog_key, connections);
          return (
            <li
              key={ref.catalog_key}
              className="flex items-center gap-3 rounded-xl px-3 py-2"
              aria-label={name}
            >
              <McpServerIcon icon={entry?.icon ?? null} name={name} />
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-medium">{name}</span>
                <span className="text-foreground/50 block text-[11px] leading-relaxed">
                  {t(`status.${status}`)}
                </span>
              </span>
              {status === "connected" ? (
                <Check className="text-brand h-4 w-4 shrink-0" aria-hidden />
              ) : status === "not_connected" && entry !== null ? (
                <Button type="button" size="sm" onClick={() => setConnecting(entry)}>
                  <Plug className="mr-1 h-3.5 w-3.5" />
                  {t("connect")}
                </Button>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => window.open(ROUTES.MCP_SERVERS, "_blank", "noopener")}
                >
                  <ExternalLink className="mr-1 h-3.5 w-3.5" />
                  {t("openServers")}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      <ConnectOwnServerDialog entry={connecting} onClose={() => setConnecting(null)} />
    </div>
  );
}
