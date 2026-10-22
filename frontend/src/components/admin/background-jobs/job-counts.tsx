"use client";

import { useTranslations } from "next-intl";

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
  counts: Record<JobStatus, number>;
  selected: JobStatus | undefined;
  onSelect: (status: JobStatus | undefined) => void;
}) {
  const t = useTranslations("pages.backgroundJobs");
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {JOB_STATUSES.map((status) => (
        <button
          key={status}
          type="button"
          aria-pressed={selected === status}
          onClick={() => onSelect(selected === status ? undefined : status)}
          className={cn(
            "border-border bg-card hover:bg-muted/60 rounded-xl border p-4 text-left transition-colors",
            selected === status && "ring-ring ring-2",
          )}
        >
          <span className="text-muted-foreground flex items-center gap-2 text-xs">
            <span aria-hidden className={cn("h-2 w-2 rounded-full", TONE[status])} />
            {t(`status.${status}`)}
          </span>
          <span className="text-foreground mt-1 block text-2xl font-semibold tabular-nums">
            {counts[status]}
          </span>
        </button>
      ))}
    </div>
  );
}
