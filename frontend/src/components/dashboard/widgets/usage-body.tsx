"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { useUsageStats } from "@/hooks";
import type { Period } from "@/lib/dashboard/period";
import type { UsageStats } from "@/types/stats";
import { cn } from "@/lib/utils";
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
  const { usage, isLoading, isStale, error, refetch } = useUsageStats({
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
  // Picking a new window holds the old answer rather than blanking ten cards
  // at once, and dims it so the numbers on screen are visibly the ones being
  // replaced. `aria-busy` says the same thing to a screen reader, which cannot
  // see the opacity.
  return (
    <div
      aria-busy={isStale || undefined}
      className={cn(
        "flex min-h-0 flex-1 flex-col transition-opacity",
        isStale && "pointer-events-none opacity-50",
      )}
    >
      {children(usage)}
    </div>
  );
}
