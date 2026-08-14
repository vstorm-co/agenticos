"use client";

import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { DASHBOARD_FRESHNESS } from "@/lib/query-freshness";
import { qk } from "@/lib/query-keys";
import type {
  AgentRun,
  AgentRunList,
  ApprovalList,
  CostSummary,
  RunStatus,
  RunTranscript,
  ToolApproval,
} from "@/types/runs";

/**
 * Run history for the organization, or for one agent.
 *
 * The two are different questions and take opposite arithmetic, which is why
 * `agentId` changes more than a filter. Without one this is the organization's
 * history and delegated rows are excluded, so the count agrees with a bill that
 * charges a parent's run once. With one it is what *that agent* did, and its
 * delegated rows are the only record of that - an agent which only ever runs as
 * somebody's delegate would otherwise show an empty history beside a spend
 * figure of forty dollars.
 *
 * One run's delegations are asked for by parent, with `useDelegatedRuns`.
 *
 * `startedFrom` windows both the rows and `total`. It exists because a count with
 * no window reads *all time* while a spend figure beside it reads one calendar
 * month, so an organization three years old showed "8,412 runs" next to "$31.20"
 * and the obvious reading of the pair was wrong by three years (#198). Any figure
 * drawn next to money passes one.
 *
 * `orderBy`/`descending`/`tookOverMs` are how the Took column sorts and the
 * "slow runs" view filters - both computed in SQL over the whole narrowed set,
 * because sorting one page of twenty-five sorts the wrong set. Only a departure
 * from the feed is put on the wire: the default order is the server's, so an
 * unfiltered call stays bodyless and keeps the same cache entry it always had.
 */
export function useRuns(
  agentId?: string,
  options?: {
    enabled?: boolean;
    startedFrom?: string;
    startedTo?: string;
    orderBy?: "started_at" | "duration" | "cost" | "tokens";
    descending?: boolean;
    tookOverMs?: number;
    rated?: "down" | "up";
    /** Narrows to these statuses - `failed,budget_exceeded` is "the problems". */
    statuses?: RunStatus[];
    surface?: string;
    /** Who the run ran as. */
    userId?: string;
    /** The frozen spec the run executed - "did v4 behave better than v3", as rows. */
    agentVersionId?: string;
    /** Rows to skip - the pager's, always a multiple of the page size. */
    skip?: number;
  },
) {
  const {
    startedFrom,
    startedTo,
    orderBy,
    descending,
    tookOverMs,
    rated,
    statuses,
    surface,
    userId,
    agentVersionId,
    skip,
  } = options ?? {};
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.list({
      agentId,
      startedFrom,
      startedTo,
      orderBy,
      descending,
      tookOverMs,
      rated,
      statuses,
      surface,
      userId,
      agentVersionId,
      skip,
    }),
    queryFn: () => {
      const params: Record<string, string> = {};
      if (agentId) {
        params.agent_id = agentId;
        params.include_delegations = "true";
      }
      if (startedFrom) params.started_from = startedFrom;
      if (startedTo) params.started_to = startedTo;
      if (orderBy && orderBy !== "started_at") params.order_by = orderBy;
      if (descending === false) params.descending = "false";
      if (tookOverMs !== undefined) params.took_over_ms = String(tookOverMs);
      // The highest-signal queue on this page: the runs somebody said were
      // wrong. A run matches if anybody rated a message it produced that way.
      if (rated) params.rated = rated;
      if (statuses && statuses.length > 0) params.status = statuses.join(",");
      if (surface) params.surface = surface;
      if (userId) params.user_id = userId;
      if (agentVersionId) params.agent_version_id = agentVersionId;
      if (skip) params.skip = String(skip);
      return apiClient.get<AgentRunList>(
        "/runs",
        Object.keys(params).length > 0 ? { params } : undefined,
      );
    },
    enabled: options?.enabled ?? true,
    // The RUNS figure and the Run history tab are left open while an agent runs
    // and read back on return, so they carry the dashboard's freshness like the
    // spend figure beside them; on the app-wide five-minute cache the list only
    // moves on a full page reload.
    ...DASHBOARD_FRESHNESS,
  });
  return { runs: data?.items ?? [], total: data?.total ?? 0, isLoading, error, refetch };
}

/**
 * One run, by id - where a link from somewhere else lands.
 *
 * Fetched on its own rather than found in the list, because the run being asked
 * about is usually a delegated one and the list deliberately does not contain
 * those. `error` is returned because a run that is gone and a run the caller may
 * not read are the same absence, and only one of them is the reader's problem.
 */
export function useRun(runId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.runs.detail(runId),
    queryFn: () => apiClient.get<AgentRun>(`/runs/${runId}`),
  });
  return { run: data, isLoading, error };
}

/**
 * A run's transcript - the turns it produced, with the ratings people gave.
 *
 * The run-detail surface reads it to show the answers rated down and the
 * comments left with them, which is where the dashboard's "quality fell four
 * points" becomes the eleven conversations that did it. `error` is returned so
 * the surface can tell a run with nothing rated down from a request that failed:
 * every page here renders its empty state on a failed query, and those two must
 * not be the same pixels.
 */
export function useRunTranscript(runId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.runs.transcript(runId),
    queryFn: () => apiClient.get<RunTranscript>(`/runs/${runId}/transcript`),
  });
  return { transcript: data, isLoading, error };
}

/** What one run delegated - the rows the top-level list leaves out. */
export function useDelegatedRuns(parentRunId: string) {
  const { data, isLoading } = useQuery({
    queryKey: qk.runs.delegations(parentRunId),
    queryFn: () => apiClient.get<AgentRunList>("/runs", { params: { parent_run_id: parentRunId } }),
  });
  return { runs: data?.items ?? [], total: data?.total ?? 0, isLoading };
}

/**
 * The approval queue.
 *
 * Polled rather than pushed: a parked run is waiting on a person who may not
 * have the page open, and a thirty-second refresh is enough for a queue whose
 * items are minutes old.
 *
 * `enabled` is how a caller without `approvals:decide` opts out, and it is not a
 * cosmetic choice: reading the queue takes the same permission as deciding one,
 * so a refused caller would answer 403 every thirty seconds for as long as the
 * page stayed open. It matters more that an empty list is then unambiguous -
 * with the query disabled there is no `[]` from a refusal for the queue to draw
 * as "nothing waiting".
 */
export function useApprovals(options?: { enabled?: boolean }) {
  const tErrors = useTranslations("errors");

  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.approvals(),
    queryFn: () => apiClient.get<ApprovalList>("/approvals"),
    refetchInterval: 30_000,
    enabled: options?.enabled ?? true,
  });

  const decide = useMutation({
    mutationFn: ({ id, approved, note }: { id: string; approved: boolean; note?: string }) =>
      apiClient.post<ToolApproval>(`/approvals/${id}`, { approved, note }),
    onSuccess: async (approval) => {
      await queryClient.invalidateQueries({ queryKey: qk.runs.all() });
      toast.success(approval.status === "approved" ? "Approved" : "Rejected");
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    approvals: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    decide,
    refetch,
  };
}

/**
 * Spend and its breakdowns, over a rolling window or an explicit one.
 *
 * The two window shapes are `GET /spend`'s own: a number of days for the
 * callers that only ever want "the last month or so" (the dashboard widgets,
 * the spending-limit control), an explicit `from`/`to` for the Activity page,
 * whose picker can name a range no rolling count reaches. `month_to_date_usd`
 * ignores the window either way - it is the invoice-reconciliation figure.
 *
 * Carries the dashboard's freshness even though the runs page and the
 * organization's spending-limit control read it too: a spend figure is the
 * last number anybody wants served from a five-minute cache, and refetching
 * it when a tab regains focus is right on all three surfaces.
 *
 * `error` is returned because the tab reading it must be able to tell a failed
 * request from a month with no spend in it. Drawn from `data` alone the two are
 * the same "nothing spent yet", and on a page about money the wrong one of those
 * is the reassuring one.
 */
export function useSpend(range: number | { from: string; to: string } = 30) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.spend(range),
    queryFn: () =>
      apiClient.get<CostSummary>("/spend", {
        params:
          typeof range === "number" ? { days: String(range) } : { from: range.from, to: range.to },
      }),
    ...DASHBOARD_FRESHNESS,
  });
  return { spend: data, isLoading, error, refetch };
}
