"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  ActivityWindow,
  BackgroundJob,
  BackgroundJobFilters,
  BackgroundJobPage,
  BackgroundJobsActivity,
  BackgroundJobsOverview,
  BackgroundKind,
} from "@/types/background-jobs";

const BASE = "/admin/background-jobs";

/**
 * Often enough to watch a backlog drain or a kind come back; the query layer stops
 * it while the tab is hidden, so a backgrounded page does not poll all day.
 */
export const OVERVIEW_REFRESH_MS = 15_000;

const PAGE_SIZE = 50;

/** The page's header: counts per status, paused kinds, live workers, schedules. */
export function useBackgroundJobsOverview() {
  return useQuery({
    queryKey: qk.admin.backgroundJobs(),
    queryFn: () => apiClient.get<BackgroundJobsOverview>(BASE),
    refetchInterval: OVERVIEW_REFRESH_MS,
  });
}

/**
 * What finished over a day or a week, by kind, and the longest wait now. A minute
 * between reads: the slices are an hour wide at the finest.
 */
export function useBackgroundJobsActivity(window: ActivityWindow) {
  return useQuery({
    queryKey: qk.admin.backgroundJobActivity(window),
    queryFn: () =>
      apiClient.get<BackgroundJobsActivity>(`${BASE}/activity`, { params: { window } }),
    refetchInterval: 60_000,
  });
}

/**
 * The queue, newest first, a keyset page at a time. The cursor is the last row's
 * `(created_at, id)`: one transaction queues many jobs at the same instant, and a
 * cursor on the time alone would skip them.
 */
export function useBackgroundJobs(filters: BackgroundJobFilters) {
  return useInfiniteQuery({
    queryKey: qk.admin.backgroundJobList({ status: filters.status, pool: filters.pool }),
    initialPageParam: null as { before: string; before_id: string } | null,
    queryFn: ({ pageParam }) => {
      const params: Record<string, string> = { limit: String(PAGE_SIZE) };
      if (filters.status) params.status = filters.status;
      if (filters.pool) params.pool = filters.pool;
      if (pageParam) {
        params.before = pageParam.before;
        params.before_id = pageParam.before_id;
      }
      return apiClient.get<BackgroundJobPage>(`${BASE}/jobs`, { params });
    },
    getNextPageParam: (page) =>
      page.next_before && page.next_before_id
        ? { before: page.next_before, before_id: page.next_before_id }
        : null,
    refetchInterval: OVERVIEW_REFRESH_MS,
  });
}

/** Retry, cancel, pause and resume - each refreshes the whole page when it lands. */
export function useBackgroundJobActions() {
  const t = useTranslations("pages.backgroundJobs");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const settle = (message: string) => ({
    onSuccess: () => {
      toast.success(message);
      void queryClient.invalidateQueries({ queryKey: qk.admin.backgroundJobs() });
    },
    onError: (error: unknown) => toast.error(getErrorMessage(error, tErrors, t("actionFailed"))),
  });

  const retry = useMutation({
    mutationFn: (job: BackgroundJob) =>
      apiClient.post<BackgroundJob>(`${BASE}/jobs/${job.id}/retry`),
    ...settle(t("retried")),
  });
  const cancel = useMutation({
    mutationFn: (job: BackgroundJob) =>
      apiClient.post<BackgroundJob>(`${BASE}/jobs/${job.id}/cancel`),
    ...settle(t("cancelled")),
  });
  // A breaker is a kind in one organization, or the whole kind: the resume names which.
  const resume = useMutation({
    mutationFn: (scope: Pick<BackgroundKind, "kind" | "organization_id">) =>
      apiClient.post<BackgroundKind>(
        `${BASE}/kinds/${scope.kind}/resume`,
        undefined,
        scope.organization_id === null
          ? undefined
          : { params: { organization_id: scope.organization_id } },
      ),
    ...settle(t("resumed")),
  });

  return { retry, cancel, resume };
}
