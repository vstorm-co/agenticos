"use client";

import Link from "next/link";
import { ClipboardCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { useReviewQueue } from "@/hooks/use-scoring";
import { ROUTES } from "@/lib/constants";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; each dataset's Scores tab has the rest. */
const SHOWN = 5;

/**
 * Eval results waiting for a person's verdict, oldest first, across the datasets
 * the reader may see - the queue a dataset's scoring fills with what did not pass.
 */
export function ReviewQueueWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.reviewQueue");
  const { scores, total, isLoading, error, refetch } = useReviewQueue({ limit: SHOWN });

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : scores.length === 0 ? (
        <WidgetEmptyBody
          icon={ClipboardCheck}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="space-y-2">
          <p className="text-muted-foreground text-xs">{t("waiting", { count: total })}</p>
          <ul className="divide-border divide-y">
            {scores.map((score) => {
              const failing = score.results.find(
                (result) => result.required && result.status !== "pass",
              );
              return (
                <li key={score.id}>
                  <Link
                    href={`${ROUTES.DATASETS}/${score.dataset_id}`}
                    className="hover:bg-accent/40 flex items-center justify-between gap-3 rounded-md px-1 py-2"
                  >
                    <span className="text-foreground truncate font-mono text-xs">
                      {failing?.name ?? t("allPassed")}
                    </span>
                    <span className="text-muted-foreground shrink-0 text-xs">
                      {score.passed === null
                        ? t("unscored")
                        : score.passed
                          ? t("passed")
                          : t("didNotPass")}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </WidgetFrame>
  );
}
