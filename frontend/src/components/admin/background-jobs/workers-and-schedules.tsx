"use client";

import { useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ListCardFootRow, PaginationBar, Skeleton } from "@/components/ui";
import { formatDateTime, timeAgo } from "@/lib/utils";
import type { BackgroundSchedule, BackgroundWorker } from "@/types/background-jobs";
import { QueueSection } from "./queue-section";

const PAGE_SIZE = 10;

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
    <>
      <PagedQueueSection
        title={t("workers")}
        count={workers && t("workersAlive", { count: workers.length })}
        items={workers}
        empty={<p className="text-destructive text-sm">{t("noWorkers")}</p>}
        renderRow={(worker) => (
          <li key={worker.id} className="px-4 py-3 sm:px-5">
            <p className="truncate font-mono text-xs font-medium">{worker.id}</p>
            <p className="text-muted-foreground text-xs">
              {t("workerLine", {
                pools: worker.pools.map((pool) => t(`pools.${pool}`)).join(", "),
                beat: timeAgo(worker.heartbeat_at, tTime, locale),
              })}
            </p>
          </li>
        )}
      />
      <PagedQueueSection
        title={t("schedules")}
        count={schedules && t("schedulesCount", { count: schedules.length })}
        items={schedules}
        empty={<p className="text-muted-foreground text-sm">{t("noSchedules")}</p>}
        renderRow={(schedule) => (
          <li
            key={schedule.name}
            className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3 sm:px-5"
          >
            <div className="min-w-0">
              <p className="truncate font-mono text-xs font-medium">{schedule.name}</p>
              <p className="text-muted-foreground text-xs">
                {t("every", interval(schedule.interval_seconds))}
              </p>
            </div>
            <p className="text-muted-foreground text-xs">
              {t("nextRun", { time: formatDateTime(schedule.next_run_at, locale) })}
            </p>
          </li>
        )}
      />
    </>
  );
}

function PagedQueueSection<T>({
  title,
  count,
  items,
  empty,
  renderRow,
}: {
  title: string;
  count?: string;
  items?: T[];
  empty?: ReactNode;
  renderRow: (item: T) => ReactNode;
}) {
  const [requestedPage, setPage] = useState(0);
  const total = items?.length ?? 0;
  const page = Math.min(requestedPage, Math.max(0, Math.ceil(total / PAGE_SIZE) - 1));
  return (
    <QueueSection title={title} count={count}>
      {items === undefined ? (
        <div className="space-y-3 p-4 sm:p-5" aria-hidden>
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : total === 0 ? (
        empty && <div className="px-4 py-3 sm:px-5">{empty}</div>
      ) : (
        <ul className="divide-border divide-y">
          {items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map(renderRow)}
        </ul>
      )}
      {total > PAGE_SIZE && (
        <ListCardFootRow>
          <PaginationBar page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} />
        </ListCardFootRow>
      )}
    </QueueSection>
  );
}

/** An interval in the largest unit it divides into, for `every`'s select. */
export function interval(seconds: number): { unit: "day" | "hour" | "minute"; count: number } {
  if (seconds % 86_400 === 0) return { unit: "day", count: seconds / 86_400 };
  if (seconds % 3_600 === 0) return { unit: "hour", count: seconds / 3_600 };
  return { unit: "minute", count: Math.max(1, Math.round(seconds / 60)) };
}
