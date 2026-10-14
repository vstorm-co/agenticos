"use client";

import Link from "next/link";
import { ClipboardCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { useReviewQueue } from "@/hooks/use-scoring";
import { ROUTES } from "@/lib/constants";
import type { PendingDataset } from "@/types/scoring";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many datasets a card lists; each dataset's Scores tab has its own queue. */
const SHOWN = 5;

const OUTCOMES = ["failed", "unscored", "passed"] as const;

/** What the scorers concluded about the scores waiting in one place: the counts that are not zero. */
function Outcomes({ counts }: { counts: Record<(typeof OUTCOMES)[number], number> }) {
  const t = useTranslations("dashboard.widgets.review-queue");
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
      {OUTCOMES.filter((outcome) => counts[outcome] > 0).map((outcome) => (
        <span key={outcome} className="bg-muted text-foreground/80 rounded px-1.5 py-0.5">
          {t(`outcome.${outcome}`, { count: counts[outcome] })}
        </span>
      ))}
    </div>
  );
}

function sum(datasets: PendingDataset[], outcome: (typeof OUTCOMES)[number]): number {
  return datasets.reduce((total, dataset) => total + dataset[outcome], 0);
}

/**
 * Eval results waiting for a person's verdict, across the datasets the reader
 * may see: how many did not pass, could not be scored, or passed and were sent
 * anyway, and which datasets hold them - each opening on its Scores tab.
 */
export function ReviewQueueWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.review-queue");
  // The card reads the breakdown, not the scores; one row keeps the page small.
  const { datasets, total, isLoading, error, refetch } = useReviewQueue({ limit: 1 });

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : total === 0 ? (
        <WidgetEmptyBody
          icon={ClipboardCheck}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="space-y-2">
          <div className="space-y-1">
            <p className="text-muted-foreground text-xs">{t("waiting", { count: total })}</p>
            <Outcomes
              counts={{
                failed: sum(datasets, "failed"),
                unscored: sum(datasets, "unscored"),
                passed: sum(datasets, "passed"),
              }}
            />
          </div>
          <ul className="divide-border divide-y">
            {datasets.slice(0, SHOWN).map((dataset) => (
              <li key={dataset.dataset_id}>
                <Link
                  href={`${ROUTES.DATASET_DETAIL(dataset.dataset_id)}?tab=scores`}
                  className="hover:bg-accent/40 flex flex-col gap-1 rounded-md px-1 py-2"
                >
                  <span className="text-foreground truncate text-sm">{dataset.name}</span>
                  <Outcomes counts={dataset} />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </WidgetFrame>
  );
}
