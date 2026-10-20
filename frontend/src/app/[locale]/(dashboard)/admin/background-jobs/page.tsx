"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ActivityCards } from "@/components/admin/background-jobs/activity-cards";
import { JobCounts } from "@/components/admin/background-jobs/job-counts";
import { JobsTable } from "@/components/admin/background-jobs/jobs-table";
import { PausedKinds } from "@/components/admin/background-jobs/paused-kinds";
import { WorkersAndSchedules } from "@/components/admin/background-jobs/workers-and-schedules";
import { ErrorState, LoadingState } from "@/components/states";
import { useBackgroundJobActions, useBackgroundJobsOverview } from "@/hooks/use-background-jobs";
import type { JobPool, JobStatus } from "@/types/background-jobs";

/**
 * The deployment's job queue, for its owner (#2219): what is waiting, what died
 * and why, which kinds the circuit breaker paused, and who is serving it.
 */
export default function BackgroundJobsPage() {
  const t = useTranslations("pages.backgroundJobs");
  const tc = useTranslations("common");
  const [status, setStatus] = useState<JobStatus | undefined>();
  const [pool, setPool] = useState<JobPool | undefined>();
  const overview = useBackgroundJobsOverview();
  const { resume } = useBackgroundJobActions();

  if (overview.isPending) return <LoadingState variant="stats" rows={4} />;
  if (overview.error || !overview.data) {
    return (
      <ErrorState
        title={t("couldNotRead")}
        description={t("couldNotReadBody")}
        cta={{ label: tc("retry"), onClick: () => void overview.refetch() }}
      />
    );
  }
  const { counts, kinds, workers, schedules } = overview.data;
  return (
    <div className="space-y-6">
      <PausedKinds
        kinds={kinds}
        onResume={(kind) => resume.mutate(kind)}
        resuming={resume.isPending ? (resume.variables ?? null) : null}
      />
      <JobCounts counts={counts} selected={status} onSelect={setStatus} />
      <ActivityCards />
      <JobsTable status={status} pool={pool} onPool={setPool} />
      <WorkersAndSchedules workers={workers} schedules={schedules} />
    </div>
  );
}
