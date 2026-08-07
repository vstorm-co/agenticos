"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { useUsageStats } from "@/hooks";
import type { Period } from "@/lib/dashboard/period";
import type { UsageStats } from "@/types/stats";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";

/**
 * The state handling every composed-response widget shares. All of them ask
 * the same query (deduped by key into one request), and all of them read
 * "zero runs in the window" as their empty state - so the split lives once.
 * `emptyKey` picks the widget's own empty copy: the states are uniform, the
 * words are not.
 */
export function UsageBody({
  period,
  emptyKey,
  children,
}: {
  period: Period;
  emptyKey: string;
  children: (usage: UsageStats) => ReactNode;
}) {
  const t = useTranslations("dashboard.widgets");
  const { usage, isLoading, error, refetch } = useUsageStats({
    from: period.from,
    to: period.to,
  });

  if (isLoading) return <WidgetSkeleton />;
  if (error) return <WidgetErrorBody onRetry={() => refetch()} />;
  if (!usage || !usage.total_runs) {
    return (
      <WidgetEmptyBody
        title={t(`${emptyKey}.empty.title`)}
        description={t(`${emptyKey}.empty.description`)}
      />
    );
  }
  return <>{children(usage)}</>;
}
