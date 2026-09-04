"use client";

import { useState } from "react";
import { Check, ExternalLink, Plug, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConnectOwnServerDialog } from "@/components/agents/connect-server-dialog";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { Button } from "@/components/ui";
import { useMcpConnections } from "@/hooks/use-mcp-connections";
import { useMcpCatalog } from "@/hooks/use-mcp-servers";
import { ownAccountStatus } from "@/lib/mcp-servers";
import type { PersonalServiceGap } from "@/types";
import type { McpCatalogEntry } from "@/types/mcp";

/**
 * The agent's personal MCP services this person cannot reach, with the button
 * that fixes it.
 *
 * Drawn from the `personal_services_unavailable` frame a turn sends before the
 * model answers, so the card is on screen while the agent is still saying it
 * cannot reach their Notion. Not part of the transcript: it is true of this
 * person at this moment, and a conversation reopened after they connected would
 * be wrong to repeat it. Dismissed, it stays away until the next question is
 * sent, which is when the parent clears the list and unmounts it.
 *
 * A service connected while the card is up - in the tab OAuth opened, or through
 * the dialog here - reads as connected the moment the connections list refetches.
 * The dialog writes the list's cache itself; the tab's consent is read when this
 * tab regains focus, which `useMcpConnections` refetches on for exactly this
 * reason. The row turns into "ask again" rather than waiting for a turn that
 * would only say the same thing.
 */
export function ConnectServicesCard({ gaps }: { gaps: PersonalServiceGap[] }) {
  const t = useTranslations("chat.personalServices");
  const { servers } = useMcpCatalog();
  const { connections } = useMcpConnections();
  const [dismissed, setDismissed] = useState(false);
  const [connecting, setConnecting] = useState<McpCatalogEntry | null>(null);
  if (dismissed) return null;

  return (
    <div
      role="status"
      className="border-border bg-card/95 rounded-2xl border p-3 shadow-sm backdrop-blur"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-muted-foreground text-xs leading-relaxed">{t("intro")}</p>
        <button
          type="button"
          aria-label={t("dismiss")}
          onClick={() => setDismissed(true)}
          className="text-muted-foreground hover:text-foreground -mt-0.5 shrink-0 rounded p-0.5"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <ul className="mt-2 space-y-1.5">
        {gaps.map((gap) => {
          const entry = servers.find((one) => one.key === gap.catalog_key) ?? null;
          // The frame said "not connected" a moment ago; the connections list is
          // what says whether that is still true.
          const connected =
            gap.gap === "not_connected" &&
            ownAccountStatus(gap.catalog_key, connections) !== "not_connected";
          return (
            <li
              key={gap.catalog_key}
              className="flex items-center gap-3 rounded-xl px-2 py-1.5"
              aria-label={gap.name}
            >
              <McpServerIcon icon={entry?.icon ?? null} name={gap.name} />
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-medium">{gap.name}</span>
                <span className="text-muted-foreground block text-[11px] leading-relaxed">
                  {connected ? t("nowConnected") : t(`gap.${gap.gap}`)}
                </span>
              </span>
              {connected ? (
                <Check className="text-brand h-4 w-4 shrink-0" aria-hidden />
              ) : gap.gap === "not_connected" && entry !== null ? (
                <Button type="button" size="sm" onClick={() => setConnecting(entry)}>
                  <Plug className="mr-1 h-3.5 w-3.5" />
                  {t("connect")}
                </Button>
              ) : (
                // A service the catalog no longer describes, or one the person
                // already holds an account on: the servers page is where that is
                // put right, and the frame carries the exact page.
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => window.open(gap.url, "_blank", "noopener")}
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
