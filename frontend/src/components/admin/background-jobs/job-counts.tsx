"use client";

import { useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { JOB_STATUSES, type JobStatus } from "@/types/background-jobs";

const TONE: Record<JobStatus, string> = {
  queued: "bg-muted-foreground",
  running: "bg-chart",
  dead: "bg-destructive",
  succeeded: "bg-chart",
  cancelled: "bg-muted-foreground",
};

/** How many jobs are in each state; choosing one filters the table below to it. */
export function JobCounts({
  counts,
  selected,
  onSelect,
}: {
  counts: Record<JobStatus, number> | undefined;
  selected: JobStatus | undefined;
  onSelect: (status: JobStatus | undefined) => void;
}) {
  const t = useTranslations("pages.backgroundJobs");
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 sm:gap-3">
      {JOB_STATUSES.map((status) => (
        <button
          key={status}
          type="button"
          disabled={counts === undefined}
          aria-pressed={selected === status}
          onClick={() => onSelect(selected === status ? undefined : status)}
          className={cn(
            "border-border bg-card hover:bg-muted/60 rounded-xl border p-3 text-left transition-colors sm:p-4",
            selected === status && "ring-ring ring-2",
          )}
        >
          <span className="text-muted-foreground flex items-center gap-1.5 text-[11px] sm:gap-2 sm:text-xs">
            <span aria-hidden className={cn("h-2 w-2 rounded-full", TONE[status])} />
            {t(`status.${status}`)}
          </span>
          <span className="text-foreground mt-1 block text-xl font-semibold tabular-nums sm:text-2xl">
            {counts === undefined ? <Skeleton className="h-8 w-12" /> : counts[status]}
          </span>
        </button>
      ))}
    </div>
  );
}
