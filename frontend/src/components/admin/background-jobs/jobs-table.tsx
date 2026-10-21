"use client";

import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import {
  Badge,
  Button,
  DataTable,
  ListCard,
  ListCardFootRow,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  type Column,
} from "@/components/ui";
import { useBackgroundJobActions, useBackgroundJobs } from "@/hooks/use-background-jobs";
import { timeAgo } from "@/lib/utils";
import type { BackgroundJob, JobPool, JobStatus } from "@/types/background-jobs";

const POOLS: readonly JobPool[] = ["agent", "ingest", "system"];
const ALL = "all";

const BADGE: Record<JobStatus, "default" | "secondary" | "destructive" | "outline"> = {
  queued: "outline",
  running: "secondary",
  succeeded: "secondary",
  dead: "destructive",
  cancelled: "outline",
};

/** The queue, newest first: filter by pool, retry what died, withdraw what has not started. */
export function JobsTable({
  status,
  pool,
  onPool,
}: {
  status: JobStatus | undefined;
  pool: JobPool | undefined;
  onPool: (pool: JobPool | undefined) => void;
}) {
  const t = useTranslations("pages.backgroundJobs");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const jobs = useBackgroundJobs({ status, pool });
  const { retry, cancel } = useBackgroundJobActions();
  const rows = jobs.data?.pages.flatMap((page) => page.items) ?? [];

  const columns = useMemo<Column<BackgroundJob>[]>(
    () => [
      {
        key: "kind",
        header: t("kind"),
        cell: (job) => (
          <div className="min-w-0">
            <p className="font-mono text-xs font-medium">{job.kind}</p>
            {job.last_error && (
              <p className="text-muted-foreground mt-1 line-clamp-2 text-xs" title={job.last_error}>
                {job.last_error}
              </p>
            )}
          </div>
        ),
      },
      {
        key: "status",
        header: t("statusColumn"),
        cell: (job) => <Badge variant={BADGE[job.status]}>{t(`status.${job.status}`)}</Badge>,
      },
      {
        key: "attempts",
        header: t("attempts"),
        align: "right",
        cell: (job) => (
          <span className="tabular-nums">
            {t("attemptsOf", { attempts: job.attempts, max: job.max_attempts })}
          </span>
        ),
      },
      { key: "pool", header: t("pool"), hideBelow: "md", cell: (job) => t(`pools.${job.pool}`) },
      {
        key: "created_at",
        header: t("queued"),
        align: "right",
        hideBelow: "sm",
        cell: (job) => (
          <span className="text-muted-foreground text-xs">
            {timeAgo(job.created_at, tTime, locale)}
          </span>
        ),
      },
      {
        key: "actions",
        header: <span className="sr-only">{t("actions")}</span>,
        align: "right",
        className: "pr-5",
        cell: (job) =>
          job.status === "dead" ? (
            <Button size="sm" variant="outline" onClick={() => retry.mutate(job)}>
              {t("retry")}
            </Button>
          ) : job.status === "queued" ? (
            <Button size="sm" variant="ghost" onClick={() => cancel.mutate(job)}>
              {t("cancel")}
            </Button>
          ) : null,
      },
    ],
    [t, tTime, locale, retry, cancel],
  );

  return (
    <ListCard
      title={t("jobs")}
      counted={t("newestFirst")}
      controls={
        <Select
          value={pool ?? ALL}
          onValueChange={(value) => onPool(value === ALL ? undefined : (value as JobPool))}
        >
          <SelectTrigger className="w-40" aria-label={t("filterByPool")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t("allPools")}</SelectItem>
            {POOLS.map((entry) => (
              <SelectItem key={entry} value={entry}>
                {t(`pools.${entry}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      }
      contentClassName="p-0"
    >
      <DataTable<BackgroundJob>
        columns={columns}
        rows={rows}
        getRowKey={(job) => job.id}
        loading={jobs.isPending}
        skeletonRows={5}
        error={
          jobs.error ? <ErrorState description={t("jobsCouldNotBeRead")} className="m-5" /> : null
        }
        empty={t("noJobs")}
        className="rounded-none border-0 bg-transparent [&_table]:min-w-[40rem]"
      />
      {jobs.hasNextPage && (
        <ListCardFootRow>
          <Button
            size="sm"
            variant="outline"
            disabled={jobs.isFetchingNextPage}
            onClick={() => void jobs.fetchNextPage()}
          >
            {t("loadMore")}
          </Button>
        </ListCardFootRow>
      )}
    </ListCard>
  );
}
