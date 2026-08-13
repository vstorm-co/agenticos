"use client";

import { Plug, RotateCw, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { BrandIcon, connectorBrand } from "@/components/icons/brand-icon";
import { SyncSourceLogs } from "@/components/rag/sync-source-logs";
import { RagStatusBadge } from "@/components/rag/rag-status-badge";
import type { SyncSourceRead } from "@/lib/rag-api";
import { formatDateTime } from "@/lib/utils";

export function SyncSourceRow({
  source,
  kbId,
  onTrigger,
  onDelete,
}: {
  source: SyncSourceRead;
  kbId: string;
  /** Absent when the caller may not write - the buttons are then not drawn. */
  onTrigger?: () => void;
  /** Asks for the disconnection; the page owns the confirmation and the call. */
  onDelete?: () => void;
}) {
  const t = useTranslations("pages.kb");
  const locale = useLocale();
  const lastSync = source.last_sync_at ? formatDateTime(source.last_sync_at, locale) : t("never");
  const brand = connectorBrand(source.connector_type);
  return (
    <li className="overflow-hidden">
      <div className="hover:bg-accent flex items-center gap-3 px-4 py-3 transition-colors">
        <span className="bg-muted text-muted-foreground inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
          {brand ? (
            <BrandIcon name={brand} className="h-4 w-4" />
          ) : (
            <Plug className="h-3.5 w-3.5" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-foreground truncate text-sm font-medium">{source.name}</p>
          </div>
          <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2 text-xs">
            <span>{t("lastSyncAt", { when: lastSync })}</span>
            {source.schedule_minutes && source.schedule_minutes > 0 && (
              <>
                <span>·</span>
                <span>{t("everyMinutes", { minutes: source.schedule_minutes })}</span>
              </>
            )}
          </div>
        </div>
        {source.last_sync_status && (
          <RagStatusBadge
            status={source.last_sync_status}
            message={source.last_error}
            className="shrink-0"
          />
        )}
        {onTrigger && (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-foreground h-8 w-8 p-0"
            onClick={onTrigger}
            title={t("triggerSyncNow")}
            aria-label={t("triggerSyncNow2")}
          >
            <RotateCw className="h-3.5 w-3.5" />
          </Button>
        )}
        {onDelete && (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-destructive h-8 w-8 p-0"
            onClick={onDelete}
            title={t("removeSource")}
            aria-label={t("removeSource2")}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
      <SyncSourceLogs logsPath={`/kb/${kbId}/sync-sources/${source.id}/logs`} />
    </li>
  );
}
