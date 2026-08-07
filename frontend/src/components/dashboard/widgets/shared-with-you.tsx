"use client";

import { useTranslations } from "next-intl";

import { useSharedWithMeCounts } from "@/hooks";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * What teammates deliberately shared with the caller, counted server-side
 * under the shared_with_me filter - never their own rows, never a page
 * counted client-side.
 */
export function SharedWithYouWidget({ title, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.shared-with-you");
  const { counts, isLoading, error, refetch } = useSharedWithMeCounts();
  const empty = counts !== null && counts.agents + counts.collections + counts.skills === 0;

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : counts === null || empty ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col justify-between gap-2">
          <div className="grid flex-1 grid-cols-3 content-center gap-2 text-center">
            {(
              [
                ["agents", counts.agents],
                ["collections", counts.collections],
                ["skills", counts.skills],
              ] as const
            ).map(([key, value]) => (
              <div key={key}>
                <p className="text-foreground text-2xl font-semibold tabular-nums">{value}</p>
                <p className="text-muted-foreground text-xs">{t(key)}</p>
              </div>
            ))}
          </div>
          <p className="text-muted-foreground text-xs">{t("subline")}</p>
        </div>
      )}
    </WidgetFrame>
  );
}
