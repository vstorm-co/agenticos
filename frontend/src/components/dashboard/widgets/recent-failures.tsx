"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useAgents, useRecentFailures } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * Failed and out-of-budget runs, newest first - the two statuses that mean
 * something needs a look, asked of /runs as a list because that is the
 * operator's actual question.
 */
export function RecentFailuresWidget({ title, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.recent-failures");
  const { failures, isLoading, error, refetch } = useRecentFailures(5);
  const { agents } = useAgents();
  const names = new Map(agents.map((agent) => [agent.id, agent.name]));

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : failures.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <ul className="space-y-2">
          {failures.map((run) => (
            <li key={run.id} className="flex items-center gap-3 text-sm">
              <span className="min-w-0 flex-1">
                <span className="text-foreground block truncate">
                  {names.get(run.agent_id) ?? t("unknownAgent")}
                </span>
                <span className="text-muted-foreground block truncate text-xs">
                  {run.status === "budget_exceeded"
                    ? t("budgetExceeded")
                    : (run.error ?? t("failed"))}
                  {run.started_at ? ` · ${timeAgo(run.started_at)}` : ""}
                </span>
              </span>
              <Link
                href={ROUTES.RUNS}
                className="text-muted-foreground hover:text-foreground shrink-0 text-xs"
              >
                {t("open")}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
