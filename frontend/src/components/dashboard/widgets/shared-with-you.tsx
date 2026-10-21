"use client";

import { useTranslations } from "next-intl";

import { Figure } from "@/components/ui";

import { useSharedWithMeCounts } from "@/hooks";
import { WidgetFrame } from "../widget-frame";
import { Share2 } from "lucide-react";

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
        // From the top, as the figure beside it in its row is: centred, the three
        // numbers sat halfway down the card while their neighbour's sat at its head.
        <div className="grid flex-1 grid-cols-3 content-start gap-4">
          {(
            [
              ["agents", counts.agents],
              ["collections", counts.collections],
              ["skills", counts.skills],
            ] as const
          ).map(([key, value]) => (
            <Figure key={key} label={t(key)} value={value.toLocaleString()} />
          ))}
        </div>
      )}
    </WidgetFrame>
  );
}
