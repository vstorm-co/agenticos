"use client";

import { useTranslations } from "next-intl";

import { useUsageStats, useVersionUsage } from "@/hooks";
import { formatMs, formatUsd } from "../format";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * Did the new version actually behave better than the old one?
 *
 * V1 picks its subject rather than offering a picker: the window's most-run
 * agent, compared across its two most recent versions that ran. Asking the
 * version question per agent is a request each, so probing every agent for
 * one with two versions would turn one card into a listing's worth of
 * queries - if the busiest agent has only one version, the card says so.
 */
export function VersionCompareWidget({ title, hint, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.version-compare");
  const window = { from: period.from, to: period.to };
  const composed = useUsageStats(window);
  const topAgent = composed.usage?.by_agent?.[0] ?? null;
  const versions = useVersionUsage(topAgent?.agent_id ?? null, window);

  const numbered = versions.byVersion.filter((row) => row.version !== null);
  const [previous, current] = numbered.slice(-2);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      {composed.isLoading || (topAgent !== null && versions.isLoading) ? (
        <WidgetSkeleton />
      ) : composed.error ? (
        <WidgetErrorBody onRetry={() => composed.refetch()} />
      ) : versions.error ? (
        <WidgetErrorBody onRetry={() => versions.refetch()} />
      ) : !topAgent || !previous || !current ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col gap-2">
          <p className="text-muted-foreground text-xs">
            {t("subline", {
              agent: topAgent.name,
              current: `v${current.version}`,
              previous: `v${previous.version}`,
            })}
          </p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted-foreground text-left text-xs">
                <th className="pb-1 font-normal" />
                <th className="pb-1 text-right font-normal">v{previous.version}</th>
                <th className="pb-1 text-right font-normal">v{current.version}</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  [t("metric.runs"), previous.runs.toLocaleString(), current.runs.toLocaleString()],
                  [
                    t("metric.completed"),
                    percent(previous.completed_runs, previous.runs),
                    percent(current.completed_runs, current.runs),
                  ],
                  [t("metric.p95"), formatMs(previous.p95_ms), formatMs(current.p95_ms)],
                  [
                    t("metric.cost"),
                    previous.avg_cost_usd !== null ? formatUsd(previous.avg_cost_usd) : "—",
                    current.avg_cost_usd !== null ? formatUsd(current.avg_cost_usd) : "—",
                  ],
                  [
                    t("metric.ratings"),
                    percent(previous.like_count, previous.rating_count),
                    percent(current.like_count, current.rating_count),
                  ],
                ] as const
              ).map(([metric, before, after]) => (
                <tr key={metric} className="border-border border-t">
                  <td className="text-muted-foreground py-1.5 pr-2 text-xs">{metric}</td>
                  <td className="py-1.5 text-right tabular-nums">{before}</td>
                  <td className="text-foreground py-1.5 text-right font-medium tabular-nums">
                    {after}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </WidgetFrame>
  );
}

function percent(part: number, whole: number): string {
  if (whole <= 0) return "—";
  return `${Math.round((part / whole) * 100)}%`;
}
