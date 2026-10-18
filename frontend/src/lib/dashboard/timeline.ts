import type { TimeBucket, UsageStats } from "@/types/stats";

const DAY_SECONDS = 86_400;

/** The window's buckets, at the step the server chose, or none on a sliced response. */
export function timelineOf(usage: UsageStats | null | undefined): TimeBucket[] {
  return usage?.timeline?.buckets ?? [];
}

/**
 * What a bucket is called on a chart's axis, at the timeline's step.
 *
 * A day step names the UTC day the way the daily series always did (`10-14`),
 * because the server bins whole days in UTC. A finer step names the reader's
 * own clock time, and the day as well once the buckets cross midnight, so
 * "15:00" is never ambiguous between yesterday and today.
 */
export function bucketLabeller(
  usage: UsageStats | null | undefined,
  locale: string,
): (bucket: TimeBucket) => string {
  const step = usage?.timeline?.step_seconds ?? DAY_SECONDS;
  if (step >= DAY_SECONDS) return (bucket) => bucket.start.slice(5, 10);
  const buckets = timelineOf(usage);
  const days = new Set(buckets.map((bucket) => new Date(bucket.start).toDateString()));
  const format = new Intl.DateTimeFormat(locale, {
    ...(days.size > 1 ? { month: "2-digit", day: "2-digit" } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
  return (bucket) => format.format(new Date(bucket.start));
}
