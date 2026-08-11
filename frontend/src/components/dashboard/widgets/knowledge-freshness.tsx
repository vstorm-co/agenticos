"use client";

import { useTranslations } from "next-intl";

import { useSyncSources } from "@/hooks";
import { timeAgo } from "@/lib/utils";
import { StatusList } from "../primitives/status-list";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** Sync sources and how fresh their collections are. */
export function KnowledgeFreshnessWidget({ title, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.knowledge-freshness");
  const tTime = useTranslations("time");
  const { sources, isLoading, error, refetch } = useSyncSources();

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : sources.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <StatusList
          rows={sources.map((source) => {
            const failing = source.last_sync_status === "failed";
            return {
              label: source.name,
              sub: failing
                ? (source.last_error ?? undefined)
                : source.last_sync_at
                  ? t("synced", { ago: timeAgo(source.last_sync_at, tTime) })
                  : t("neverSynced"),
              pill: failing ? t("failing") : t("fresh"),
              tone: failing ? ("err" as const) : ("ok" as const),
            };
          })}
        />
      )}
    </WidgetFrame>
  );
}
