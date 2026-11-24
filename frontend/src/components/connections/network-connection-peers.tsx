"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Skeleton } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import type { NetworkConnectionScopeKey } from "@/types/network-connections";
import { useNetworkPeers } from "@/hooks/use-network-connections";

export function NetworkConnectionPeers({
  id,
  scope,
}: {
  id: string;
  scope: NetworkConnectionScopeKey | null;
}) {
  const t = useTranslations("networkConnections");
  const tErrors = useTranslations("errors");
  const [expanded, setExpanded] = useState(false);
  const query = useNetworkPeers(id, scope, expanded);

  return (
    <section className="border-border border-t pt-3">
      <Button
        variant="ghost"
        size="sm"
        aria-expanded={expanded}
        onClick={() => setExpanded((open) => !open)}
      >
        {expanded ? <ChevronUp aria-hidden /> : <ChevronDown aria-hidden />}
        {t(expanded ? "peers.hide" : "peers.show")}
      </Button>
      {expanded && (
        <div className="mt-3 space-y-3">
          <p className="text-muted-foreground text-xs">{t("peers.disclaimer")}</p>
          {query.isLoading && <Skeleton className="h-20 rounded-lg" />}
          {query.error && (
            <p role="alert" className="text-destructive text-sm">
              {getErrorMessage(query.error, tErrors)}
            </p>
          )}
          {query.data?.items.length === 0 && (
            <p className="text-muted-foreground text-sm">{t("peers.empty")}</p>
          )}
          {query.data?.items.map((peer) => (
            <article key={peer.id} className="bg-muted/40 rounded-lg p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{peer.hostname}</span>
                <span
                  className={
                    peer.online ? "text-green-700 dark:text-green-400" : "text-muted-foreground"
                  }
                >
                  {t(peer.online ? "peers.online" : "peers.offline")}
                </span>
              </div>
              <dl className="text-muted-foreground mt-2 grid gap-x-3 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
                <dt>{t("peers.dnsName")}</dt>
                <dd className="break-all">{peer.dns_name || "—"}</dd>
                <dt>{t("peers.ips")}</dt>
                <dd className="break-all">{peer.ips.length ? peer.ips.join(", ") : "—"}</dd>
                <dt>{t("peers.os")}</dt>
                <dd>{peer.os || "—"}</dd>
              </dl>
            </article>
          ))}
          {query.data?.observed_at && (
            <p className="text-muted-foreground text-xs">
              {t("peers.observed", { time: new Date(query.data.observed_at).toLocaleString() })}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
