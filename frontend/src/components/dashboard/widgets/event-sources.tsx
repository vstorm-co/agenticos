"use client";

import { Plug } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { Figure } from "@/components/ui";
import { useEventSources } from "@/hooks/use-event-sources";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

export function EventSourcesWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.event-sources");
  const format = useFormatter();
  const { data, isLoading, error, refetch } = useEventSources();
  const sources = data?.items ?? [];
  const active = sources.filter((source) => source.is_active).length;

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : sources.length === 0 ? (
        <WidgetEmptyBody icon={Plug} title={t("empty")} />
      ) : (
        <div className="grid grid-cols-2 gap-4">
          <Figure label={t("active")} value={format.number(active)} />
          <Figure label={t("paused")} value={format.number(sources.length - active)} />
        </div>
      )}
    </WidgetFrame>
  );
}
