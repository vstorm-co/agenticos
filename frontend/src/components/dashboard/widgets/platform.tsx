"use client";

import { useTranslations } from "next-intl";

import { useAdminStats } from "@/hooks";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** Deployment-wide counts. The one strip an org admin never sees. */
export function PlatformWidget({ title, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.platform");
  const { stats, isLoading, error, refetch } = useAdminStats();

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !stats || !stats.total_organizations ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="grid flex-1 grid-cols-2 gap-4 lg:grid-cols-4">
          {(
            [
              ["organizations", stats.total_organizations, null],
              ["users", stats.total_users, t("active24h", { count: stats.active_users_24h ?? 0 })],
              ["agents", stats.total_agents, null],
              ["conversations", stats.total_conversations, null],
            ] as const
          ).map(([key, value, sub]) => (
            <div key={key}>
              <p className="text-muted-foreground text-xs">{t(key)}</p>
              <p className="text-foreground text-2xl font-semibold tabular-nums">
                {(value ?? 0).toLocaleString()}
              </p>
              {sub ? <p className="text-muted-foreground text-xs">{sub}</p> : null}
            </div>
          ))}
        </div>
      )}
    </WidgetFrame>
  );
}
