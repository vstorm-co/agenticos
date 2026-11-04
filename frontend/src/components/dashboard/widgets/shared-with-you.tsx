"use client";

import { useTranslations } from "next-intl";

import { useSharedWithMeCounts } from "@/hooks";
import { WidgetFrame } from "../widget-frame";
import { Bot, LibraryBig, Share2, Waypoints } from "lucide-react";

import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * What teammates deliberately shared with the caller, counted server-side
 * under the shared_with_me filter - never their own rows, never a page
 * counted client-side.
 */
export function SharedWithYouWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.shared-with-you");
  const { counts, isLoading, error, refetch } = useSharedWithMeCounts();
  const empty = counts !== null && counts.agents + counts.collections + counts.skills === 0;

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : counts === null || empty ? (
        <WidgetEmptyBody
          icon={Share2}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="space-y-2">
          {(
            [
              ["agents", counts.agents, Bot],
              ["collections", counts.collections, LibraryBig],
              ["skills", counts.skills, Waypoints],
            ] as const
          ).map(([key, value, Icon]) => (
            <li key={key} className="flex items-center gap-3 py-1.5">
              <span
                className="bg-foreground/[0.04] text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-lg"
                aria-hidden
              >
                <Icon className="size-4" />
              </span>
              <span className="text-foreground min-w-0 flex-1 text-sm font-medium">{t(key)}</span>
              <span className="text-muted-foreground text-sm tabular-nums">
                {value.toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
