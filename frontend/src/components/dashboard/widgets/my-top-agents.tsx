"use client";

import { useTranslations } from "next-intl";

import { useUsageStats } from "@/hooks";
import { AgentFace } from "../agent-face";
import { WidgetFrame } from "../widget-frame";
import { Bot } from "lucide-react";

import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** The caller's own favourites - their runs in the window, nobody else's. */
export function MyTopAgentsWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.my-top-agents");
  const { usage, isLoading, error, refetch } = useUsageStats(
    { from: period.from, to: period.to },
    { scope: "own" },
  );

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton variant="bars" />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !usage || !usage.total_runs ? (
        <WidgetEmptyBody icon={Bot} title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <ul className="divide-border/60 divide-y">
          {(usage.by_agent ?? []).slice(0, 3).map((row) => (
            <li key={row.agent_id} className="flex items-center gap-3 py-2 first:pt-0 last:pb-0">
              <AgentFace agentId={row.agent_id} className="size-9" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{row.name}</span>
              <span className="text-foreground text-sm font-semibold tabular-nums">{row.runs}</span>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
