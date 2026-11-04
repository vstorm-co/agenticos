"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ScrollText } from "lucide-react";

import { Figure } from "@/components/ui";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";
import { useRecentWorkflowLogs } from "@/hooks";
import { LogOutcome } from "@/components/workflows/logs/workflow-logs";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";

/** How many of the newest lines the card draws. */
const SHOWN_LINES = 6;

/**
 * What the workflows the reader may view wrote to their logs lately: the last
 * 24 hours' lines and how many of them were errors, then the newest few, each
 * linking to its run and its workflow's Logs page. Real runs only. The card
 * ignores the dashboard's period - "lately" is the last day, whatever it is set to.
 */
export function WorkflowLogsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.workflow-logs");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { logs, isLoading, error, refetch } = useRecentWorkflowLogs(SHOWN_LINES);

  const lastDay = Object.values(logs?.counts ?? {}).reduce((sum, lines) => sum + lines, 0);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error || !logs ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : logs.items.length === 0 ? (
        <WidgetEmptyBody
          icon={ScrollText}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="flex flex-1 flex-col gap-4">
          <div className="grid grid-cols-2 gap-4">
            <Figure label={t("lastDay")} value={lastDay.toLocaleString(locale)} />
            <Figure
              label={t("errors")}
              value={(logs.counts["error"] ?? 0).toLocaleString(locale)}
              tone={(logs.counts["error"] ?? 0) > 0 ? "rose" : undefined}
            />
          </div>
          <ul className="divide-border divide-y">
            {logs.items.map((entry) => (
              <li key={entry.id} className="flex flex-col gap-0.5 py-1.5 text-sm">
                <Link
                  href={ROUTES.WORKFLOW_RUN_DETAIL(entry.workflow_id, entry.run_id)}
                  className="hover:text-foreground truncate"
                  title={entry.message}
                >
                  {entry.message}
                </Link>
                <span className="text-muted-foreground flex items-center gap-1 text-xs">
                  <Link
                    href={ROUTES.WORKFLOW_LOGS(entry.workflow_id)}
                    className="hover:text-foreground truncate"
                  >
                    {entry.workflow_name}
                  </Link>
                  <span className="shrink-0">{`· ${entry.step_label} ·`}</span>
                  <LogOutcome entry={entry} />
                  <span className="shrink-0">{`· ${timeAgo(entry.created_at, tTime, locale)}`}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </WidgetFrame>
  );
}
