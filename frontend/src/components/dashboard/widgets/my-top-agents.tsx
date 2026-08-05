"use client";

import { useTranslations } from "next-intl";

import { useUsageStats } from "@/hooks";
import { BarList } from "../primitives/bar-list";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** The caller's own favourites - their runs in the window, nobody else's. */
export function MyTopAgentsWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.my-top-agents");
  const { usage, isLoading, error, refetch } = useUsageStats(
    { from: period.from, to: period.to },
    { scope: "own" },
  );

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !usage || !usage.total_runs ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col justify-between gap-2">
          <BarList
            items={(usage.by_agent ?? [])
              .slice(0, 4)
              .map((row) => ({ label: row.name, value: row.runs }))}
          />
          <p className="text-muted-foreground text-xs">{t("subline")}</p>
        </div>
      )}
    </WidgetFrame>
  );
}
