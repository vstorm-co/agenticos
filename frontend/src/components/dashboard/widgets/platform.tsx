"use client";

import { useTranslations } from "next-intl";

import { useAdminStats } from "@/hooks";
import { Metric } from "../metric";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** Deployment-wide counts. The one strip an org admin never sees. */
export function PlatformWidget({ title, hint, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.platform");
  const { stats, isLoading, error, refetch } = useAdminStats();

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !stats || !stats.total_organizations ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="grid flex-1 grid-cols-2 content-center gap-5 lg:grid-cols-4">
          {(
            [
              ["organizations", stats.total_organizations, null],
              ["users", stats.total_users, t("active24h", { count: stats.active_users_24h ?? 0 })],
              ["agents", stats.total_agents, null],
              ["conversations", stats.total_conversations, null],
            ] as const
          ).map(([key, value, sub]) => (
            <Metric
              key={key}
              label={t(key)}
              value={(value ?? 0).toLocaleString()}
              caption={sub ?? undefined}
            />
          ))}
        </div>
      )}
    </WidgetFrame>
  );
}
