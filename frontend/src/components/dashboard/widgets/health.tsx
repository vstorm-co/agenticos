"use client";

import { useTranslations } from "next-intl";

import { useSystemHealth } from "@/hooks";
import type { CheckStatus } from "@/types/admin";
import { StatusList, type StatusTone } from "../primitives/status-list";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

const TONE: Record<CheckStatus, StatusTone> = {
  healthy: "ok",
  unhealthy: "err",
  unconfigured: "neutral",
  not_checked: "neutral",
};

/** The deployment's service probes, as the admin system page reports them. */
export function HealthWidget({ title, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.health");
  const { health, isLoading, error, refetch } = useSystemHealth();

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : !health || health.checks.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <StatusList
          rows={health.checks.map((check) => ({
            label: check.key.replace(/_/g, " "),
            sub: check.status === "healthy" ? undefined : check.detail,
            pill: t(`status.${check.status}`),
            tone: TONE[check.status],
          }))}
        />
      )}
    </WidgetFrame>
  );
}
