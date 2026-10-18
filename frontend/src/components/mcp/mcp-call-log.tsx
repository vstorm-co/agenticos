"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useOrgMcpToolCalls } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import { cn, timeAgo } from "@/lib/utils";

/**
 * What agents asked one of the organization's servers to do (#2072).
 *
 * The tool, the agent, how it went and when - and a link to the run, for whoever
 * may open it. Never the arguments or the result: those are the conversation's,
 * and whoever manages a server is not thereby a reader of every chat using it.
 * Mounted only while open, so the log is fetched only when somebody asks.
 */
export function McpCallLog({
  connection,
  onClose,
}: {
  connection: McpConnectionRecord;
  onClose: () => void;
}) {
  const t = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { calls, isLoading, error } = useOrgMcpToolCalls(connection.id);

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>
            {t("callLogTitle", { name: connection.label ?? connection.name })}
          </DialogTitle>
          <DialogDescription>{t("callLogWhy")}</DialogDescription>
        </DialogHeader>
        {error ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : isLoading ? (
          <LoadingState variant="skeleton-list" rows={4} />
        ) : calls.length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">{t("callLogEmpty")}</p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {calls.map((call, index) => (
              <li
                key={`${call.started_at}-${index}`}
                className="flex items-center gap-3 px-3 py-2 text-sm"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-xs">{call.tool}</span>
                  <span className="text-muted-foreground block truncate text-xs">
                    {call.agent_name ?? t("callLogNoAgent")}
                    {" · "}
                    {timeAgo(call.started_at, tTime, locale)}
                    {call.duration_ms !== null &&
                      ` · ${t("callLogDuration", { ms: call.duration_ms })}`}
                  </span>
                </span>
                <Badge variant={call.status === "failed" ? "destructive" : "outline"}>
                  {t.has(`callStatus.${call.status}`)
                    ? t(`callStatus.${call.status}`)
                    : call.status}
                </Badge>
                {call.run_id && (
                  <Link
                    href={`${ROUTES.RUNS}?run=${call.run_id}`}
                    className="text-muted-foreground hover:text-foreground text-xs underline"
                  >
                    {t("callLogRun")}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
