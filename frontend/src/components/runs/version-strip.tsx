"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { formatMs, formatUsd } from "@/components/dashboard/format";
import { ErrorState } from "@/components/states";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui";
import { useAgent, useVersionUsage } from "@/hooks";
import { DEFAULT_PRESET, resolvePreset } from "@/lib/dashboard/period";
import { completedShare, formatCompletedShare, versionTally } from "@/lib/run-outcomes";
import type { VersionUsageRow } from "@/types/stats";

/**
 * Per-version summary for the agent the Runs tab is narrowed to.
 *
 * One card per version that ran in the window: how many runs it served, the
 * share that completed, its cost per run, and its p95. The completed share is
 * the shared `completedShare` - `completed / total` with nothing excluded - so
 * it prints as the same number the dashboard's Outcomes donut shows over the
 * same rows, which is the whole point of §8a.4: two screens reading one
 * `by_status` must not drift apart under one word.
 *
 * Runs count what the agent did as somebody's delegate too, so a specialist
 * used only as a delegate is not left with an empty strip; cost per run is an
 * average of the agent's own rows, so it never counts a delegation twice the
 * way a sum across a parent and its child would (activity-plan.md §2a, §6).
 */
export function VersionStrip({ agentId }: { agentId: string }) {
  const t = useTranslations("pages.runs");
  const period = useMemo(() => resolvePreset(DEFAULT_PRESET), []);
  const { byVersion, isLoading, error, refetch } = useVersionUsage(agentId, period);
  const { agent } = useAgent(agentId);
  const currentVersionId = agent?.current_version_id ?? null;

  if (isLoading) {
    return <Skeleton className="h-28 w-full" />;
  }
  if (error) {
    return (
      <ErrorState
        title={t("versionStripCouldNot")}
        description={t("theseRunsHappenedThe")}
        cta={{ label: t("tryAgain"), onClick: () => void refetch() }}
      />
    );
  }
  if (byVersion.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("versionsTitle")}</CardTitle>
        <CardDescription>{t("versionsCaption")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {byVersion.map((row) => (
          <VersionCard
            key={row.agent_version_id ?? "deleted"}
            row={row}
            isCurrent={row.agent_version_id !== null && row.agent_version_id === currentVersionId}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function VersionCard({ row, isCurrent }: { row: VersionUsageRow; isCurrent: boolean }) {
  const t = useTranslations("pages.runs");
  const label = row.version !== null ? `v${row.version}` : t("deletedVersion");
  const share = formatCompletedShare(completedShare(versionTally(row)));
  const costPerRun = row.avg_cost_usd !== null ? formatUsd(row.avg_cost_usd) : "—";

  return (
    <div className="border-border space-y-2 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <span className="text-foreground text-sm font-medium tabular-nums">{label}</span>
        {isCurrent && <Badge variant="secondary">{t("currentVersion")}</Badge>}
      </div>
      <p className="text-muted-foreground text-xs">{t("runCount", { count: row.runs })}</p>
      <dl className="grid grid-cols-3 gap-2 text-xs">
        <Stat value={share} label={t("perVersionCompleted")} />
        <Stat value={costPerRun} label={t("perVersionCostPerRun")} />
        <Stat value={formatMs(row.p95_ms)} label={t("perVersionLatency")} />
      </dl>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground font-medium tabular-nums">{value}</dd>
    </div>
  );
}
