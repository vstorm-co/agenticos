"use client";

import { useState } from "react";
import { Plug, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { EmptyState, ErrorState } from "@/components/states";
import { SyncSourceRow } from "@/components/rag/sync-source-row";
import type { ConnectorInfo, SyncSourceRead } from "@/lib/rag-api";

// Sync sources have no server-side pagination (the backend returns every source
// for the KB's collection). They're typically few, so collapse past this count
// behind a client-side "show all" toggle.
const SYNC_SOURCES_VISIBLE = 10;

/**
 * Where the collection keeps itself in step with somewhere else.
 *
 * Two failures reach this section and they are not the same one, which is why
 * both arrive as their own flag rather than as an empty list. A failed sync-source
 * list must not render "none connected", and a failed *connector* list must not
 * silently hide the Connect button - a capability that disappears without a
 * reason reads as a product that does not have it.
 */
export function SyncSourcesSection({
  kbId,
  syncSources,
  connectors,
  syncSourcesFailed,
  connectorsFailed,
  mayEdit,
  onConnect,
  onTrigger,
  onDisconnect,
  onRetry,
}: {
  kbId: string;
  syncSources: SyncSourceRead[];
  connectors: ConnectorInfo[];
  /** The list failed to load - distinct from it loading empty. */
  syncSourcesFailed: boolean;
  /** The connector catalog failed to load, which is what hides Connect. */
  connectorsFailed: boolean;
  mayEdit: boolean;
  onConnect: () => void;
  onTrigger: (sourceId: string) => void;
  onDisconnect: (source: SyncSourceRead) => void;
  onRetry: () => void;
}) {
  const t = useTranslations("pages.kb");
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? syncSources : syncSources.slice(0, SYNC_SOURCES_VISIBLE);

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-foreground text-sm font-semibold">{t("syncSources")}</h2>
        {mayEdit && connectors.length > 0 && (
          <Button variant="outline" size="sm" onClick={onConnect}>
            <Plus className="h-4 w-4" />
            {t("connect")}
          </Button>
        )}
      </div>

      {/* Its own line rather than a branch of the states below, because a failed
          connector list is orthogonal to whether any sources loaded: it is what
          hides the Connect button above, and hiding a capability without saying
          why reads as the product not having it. */}
      {connectorsFailed && (
        <div className="mb-3">
          <ErrorState
            title={t("connectorsFailedTitle")}
            description={t("connectorsFailedDescription")}
            cta={{ label: t("retry"), onClick: onRetry }}
          />
        </div>
      )}

      {syncSourcesFailed ? (
        <ErrorState
          title={t("syncSourcesFailedTitle")}
          description={t("syncSourcesFailedDescription")}
          cta={{ label: t("retry"), onClick: onRetry }}
        />
      ) : syncSources.length > 0 ? (
        <>
          <ul className="border-border bg-card divide-border divide-y overflow-hidden rounded-xl border">
            {visible.map((source) => (
              <SyncSourceRow
                key={source.id}
                source={source}
                kbId={kbId}
                onTrigger={mayEdit ? () => onTrigger(source.id) : undefined}
                onDelete={mayEdit ? () => onDisconnect(source) : undefined}
              />
            ))}
          </ul>
          {syncSources.length > SYNC_SOURCES_VISIBLE && (
            <div className="mt-3 flex justify-center">
              <Button variant="outline" size="sm" onClick={() => setExpanded((v) => !v)}>
                {expanded ? t("showLess") : t("showAllSources", { count: syncSources.length })}
              </Button>
            </div>
          )}
        </>
      ) : connectorsFailed ? null : (
        // No sources, and the connector list did load: "none connected" and
        // "none configured" are both facts here, and the notice above has
        // already spoken for the case where neither is established.
        <EmptyState
          icon={Plug}
          title={connectors.length > 0 ? t("noSourcesConnected") : t("noConnectorsConfigured")}
          description={
            connectors.length > 0 ? t("addOneKeepKnowledge") : t("configureConnectorsAtWorkspace")
          }
          cta={
            mayEdit && connectors.length > 0
              ? { label: t("connectSource"), onClick: onConnect }
              : undefined
          }
        />
      )}
    </section>
  );
}
