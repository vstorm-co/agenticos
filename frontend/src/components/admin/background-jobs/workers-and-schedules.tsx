"use client";

import { useLocale, useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";
import { ListCard } from "@/components/ui";
import { formatDateTime, timeAgo } from "@/lib/utils";
import type { BackgroundSchedule, BackgroundWorker } from "@/types/background-jobs";

/** Who is serving the queue right now, and when each recurring job next runs. */
export function WorkersAndSchedules({
  workers,
  schedules,
}: {
  workers: BackgroundWorker[] | undefined;
  schedules: BackgroundSchedule[] | undefined;
}) {
  const t = useTranslations("pages.backgroundJobs");
  const tTime = useTranslations("time");
  const locale = useLocale();
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <ListCard
        title={t("workers")}
        counted={workers ? t("workersAlive", { count: workers.length }) : null}
      >
        {workers === undefined ? (
          <PendingRows />
        ) : workers.length === 0 ? (
          <p className="text-destructive text-sm">{t("noWorkers")}</p>
        ) : (
          <ul className="divide-border divide-y">
            {workers.map((worker) => (
              <li key={worker.id} className="py-2.5 first:pt-0 last:pb-0">
                <p className="truncate font-mono text-xs font-medium">{worker.id}</p>
                <p className="text-muted-foreground text-xs">
                  {t("workerLine", {
                    pools: worker.pools.map((pool) => t(`pools.${pool}`)).join(", "),
                    beat: timeAgo(worker.heartbeat_at, tTime, locale),
                  })}
                </p>
              </li>
            ))}
          </ul>
        )}
      </ListCard>
      <ListCard
        title={t("schedules")}
        counted={schedules ? t("schedulesCount", { count: schedules.length }) : null}
      >
        {schedules === undefined ? (
          <PendingRows />
        ) : (
          <ul className="divide-border divide-y">
            {schedules.map((schedule) => (
              <li key={schedule.name} className="flex items-baseline justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate font-mono text-xs font-medium">{schedule.name}</p>
                  <p className="text-muted-foreground text-xs">
                    {t("every", interval(schedule.interval_seconds))}
                  </p>
                </div>
                <p className="text-muted-foreground shrink-0 text-xs">
                  {t("nextRun", { time: formatDateTime(schedule.next_run_at, locale) })}
                </p>
              </li>
            ))}
          </ul>
        )}
      </ListCard>
    </div>
  );
}

/** An interval in the largest unit it divides into, for `every`'s select. */
export function interval(seconds: number): { unit: "day" | "hour" | "minute"; count: number } {
  if (seconds % 86_400 === 0) return { unit: "day", count: seconds / 86_400 };
  if (seconds % 3_600 === 0) return { unit: "hour", count: seconds / 3_600 };
  return { unit: "minute", count: Math.max(1, Math.round(seconds / 60)) };
}

function PendingRows() {
  return (
    <ul className="divide-border divide-y" aria-hidden>
      {[0, 1, 2].map((row) => (
        <li key={row} className="space-y-1 py-2.5 first:pt-0 last:pb-0">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-4 w-2/3" />
        </li>
      ))}
    </ul>
  );
}
