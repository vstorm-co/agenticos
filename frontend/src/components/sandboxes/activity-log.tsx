"use client";

import { useMemo } from "react";

import { DataTable, Skeleton, type Column } from "@/components/ui";
import { useSandboxEvents } from "@/hooks";
import type { SandboxEvent } from "@/lib/sandbox-connections-api";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

interface ActivityLogProps {
  connectionId: string;
  sessionId: string;
}

/**
 * What was done to one sandbox.
 *
 * Paths and commands, never their contents or output — the service does not
 * record those, which is what keeps this from becoming a way to read an agent's
 * work rather than audit it.
 */
export function ActivityLog({ connectionId, sessionId }: ActivityLogProps) {
  const t = useTranslations("sandboxes");
  const { log, isLoading, error } = useSandboxEvents(connectionId, sessionId);

  const columns = useMemo<Column<SandboxEvent>[]>(
    () => [
      {
        key: "op",
        header: t("sessions.operation"),
        className: "pl-5",
        cell: (event) => (
          <span className={cn("font-mono text-xs", !event.ok && "text-destructive")}>
            {event.op}
          </span>
        ),
      },
      {
        key: "target",
        header: t("sessions.target"),
        cell: (event) => (
          <span className={cn("font-mono text-xs break-all", !event.ok && "text-destructive")}>
            {event.target}
          </span>
        ),
      },
      {
        key: "detail",
        header: t("sessions.detail"),
        cell: (event) => (
          <span className={cn("text-xs", event.ok ? "text-muted-foreground" : "text-destructive")}>
            {event.detail}
          </span>
        ),
      },
      {
        key: "duration",
        header: t("sessions.duration"),
        align: "right",
        className: "pr-5",
        cell: (event) => (
          <span className="text-muted-foreground text-xs">{`${Math.round(event.duration_ms)}ms`}</span>
        ),
      },
    ],
    [t],
  );

  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (error !== null) return <p className="text-destructive text-sm">{error}</p>;
  if (log === null || log.events.length === 0)
    return (
      <p className="text-muted-foreground text-sm">
        {t.rich("nothingRecordedYet", {
          session: sessionId,
          id: (chunks) => <span className="font-mono">{chunks}</span>,
        })}
      </p>
    );

  return (
    <div className="max-h-64 overflow-auto">
      <DataTable<SandboxEvent>
        columns={columns}
        rows={log.events}
        getRowKey={(event) => String(event.seq)}
      />
    </div>
  );
}
