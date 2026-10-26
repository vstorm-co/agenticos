"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { SEGMENTED_CLASS, segment } from "@/components/dashboard/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { ListCard } from "@/components/ui";
import { useBackgroundJobsActivity } from "@/hooks/use-background-jobs";
import type { ActivityWindow } from "@/types/background-jobs";
import { ActivityChart, ActivityFigures, KindActivityTable } from "./job-activity";

const WINDOWS: readonly ActivityWindow[] = ["day", "week"];

/**
 * What the queue did over a day or a week (#2248): the figures, the finished
 * jobs per slice by outcome, and each kind's volume and timings. Counts alone
 * said what is in the table now, and nothing about whether it is keeping up.
 */
export function ActivityCards() {
  const t = useTranslations("pages.backgroundJobs");
  const [span, setSpan] = useState<ActivityWindow>("day");
  const activity = useBackgroundJobsActivity(span);
  const switcher = (
    <div className={SEGMENTED_CLASS} role="group" aria-label={t("windowLabel")}>
      {WINDOWS.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={span === option}
          className={segment(span === option)}
          onClick={() => setSpan(option)}
        >
          {t(`window.${option}`)}
        </button>
      ))}
    </div>
  );
  return (
    <div className="space-y-6">
      <ListCard
        title={t("activity")}
        counted={activity.data ? t("finishedCaption", { window: span }) : null}
        controls={switcher}
      >
        {activity.error ? (
          <p className="text-destructive text-sm">{t("activityCouldNotBeRead")}</p>
        ) : !activity.data ? (
          <div className="space-y-6" aria-hidden>
            <div className="grid grid-cols-2 gap-5 lg:grid-cols-4">
              {[0, 1, 2, 3].map((figure) => (
                <div key={figure} className="space-y-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-8 w-20" />
                  <Skeleton className="h-4 w-28" />
                </div>
              ))}
            </div>
            <Skeleton className="h-56 w-full" />
          </div>
        ) : (
          <div className="space-y-6">
            <ActivityFigures activity={activity.data} />
            <ActivityChart activity={activity.data} className="h-56" />
          </div>
        )}
      </ListCard>
      <ListCard
        title={t("byKind")}
        counted={activity.data ? t("kindsCount", { count: activity.data.kinds.length }) : null}
      >
        {activity.data ? (
          <KindActivityTable kinds={activity.data.kinds} />
        ) : !activity.error ? (
          <div className="space-y-3" aria-hidden>
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-8 w-full" />
            ))}
          </div>
        ) : null}
      </ListCard>
    </div>
  );
}
