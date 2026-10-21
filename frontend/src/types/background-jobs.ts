/**
 * The deployment's background job queue, as its owner reads it (#2219).
 *
 * Mirrors `app/schemas/background_job.py`. A job's payload is never sent: it
 * carries ids, and the page shows what happened to the job, not what it was for.
 */

export type JobStatus = "queued" | "running" | "succeeded" | "dead" | "cancelled";
export type JobPool = "agent" | "ingest" | "system";

export const JOB_STATUSES: readonly JobStatus[] = [
  "queued",
  "running",
  "dead",
  "succeeded",
  "cancelled",
];

export interface BackgroundJob {
  id: string;
  kind: string;
  pool: JobPool;
  status: JobStatus;
  priority: number;
  attempts: number;
  max_attempts: number;
  organization_id: string | null;
  schedule_name: string | null;
  worker_id: string | null;
  last_error: string | null;
  run_after: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface BackgroundJobPage {
  items: BackgroundJob[];
  next_before: string | null;
  next_before_id: string | null;
}

export interface BackgroundKind {
  kind: string;
  /** The organization this breaker is for; null for the whole kind (#2248). */
  organization_id: string | null;
  organization_name: string | null;
  consecutive_deaths: number;
  lease_lost: number;
  paused_at: string | null;
  paused_reason: string | null;
}

export interface BackgroundWorker {
  id: string;
  hostname: string;
  pools: string[];
  started_at: string;
  heartbeat_at: string;
}

export interface BackgroundSchedule {
  name: string;
  kind: string;
  interval_seconds: number;
  next_run_at: string;
  last_fired_at: string | null;
  overlap: string;
  misfire: string;
}

export interface BackgroundJobsOverview {
  counts: Record<JobStatus, number>;
  kinds: BackgroundKind[];
  workers: BackgroundWorker[];
  schedules: BackgroundSchedule[];
}

/** The span the page charts: a day in hourly slices, or a week in six-hour ones. */
export type ActivityWindow = "day" | "week";

export interface FinishedBucket {
  start: string;
  succeeded: number;
  dead: number;
  cancelled: number;
}

export interface KindActivity {
  kind: string;
  pool: JobPool;
  finished: number;
  dead: number;
  run_p50_seconds: number | null;
  run_p95_seconds: number | null;
  wait_p95_seconds: number | null;
}

export interface BackgroundJobsActivity {
  window: ActivityWindow;
  bucket_seconds: number;
  buckets: FinishedBucket[];
  kinds: KindActivity[];
  oldest_wait_seconds: number | null;
}

export interface BackgroundJobFilters {
  status?: JobStatus;
  pool?: JobPool;
}
