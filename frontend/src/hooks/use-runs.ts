"use client";

import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { ApiError, apiClient } from "@/lib/api-client";
import { DASHBOARD_FRESHNESS } from "@/lib/query-freshness";
import { qk } from "@/lib/query-keys";
import type {
  AgentRun,
  AgentRunList,
  ApprovalList,
  CostSummary,
  RunStatus,
  ResumedRun,
  RunManifest,
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
    /** The model as the run recorded it - the dashboard's bars count these. */
    modelLabel?: string;
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
    modelLabel,
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
      modelLabel,
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
      if (modelLabel) params.model_label = modelLabel;
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
    // Hold the run being read while the next one is in flight. Stepping through
    // a conversation is a new query key per run, so without this every arrow
    // press drops the whole detail to a skeleton and rebuilds it - the page
    // blanks, reflows and comes back, on a surface whose entire purpose is
    // reading several runs in a row. The caller can tell what it is holding:
    // `data.id` is the run this answer is about, not the one asked for.
    placeholderData: keepPreviousData,
  });
  return { run: data, isLoading, error };
}

/**
 * Warm the neighbours of the run being read, so an arrow press is a cache hit.
 *
 * Both queries the detail view makes, for both directions, at the moment the
 * reader arrives - which is the moment they are least likely to be waiting on
 * anything. Stepping then renders from cache with no request in flight at all,
 * where holding the previous answer only hides a wait that still happens.
 *
 * `staleTime` is what makes it worth doing: prefetched with the app-wide
 * default of five minutes, the step reuses the row rather than re-asking for it
 * the moment it is rendered.
 */
export function usePrefetchRuns(runIds: (string | null | undefined)[]) {
  const queryClient = useQueryClient();
  const ids = runIds.filter((id): id is string => typeof id === "string");
  const key = ids.join(",");
  useEffect(() => {
    for (const id of key === "" ? [] : key.split(",")) {
      void queryClient.prefetchQuery({
        queryKey: qk.runs.detail(id),
        queryFn: () => apiClient.get<AgentRun>(`/runs/${id}`),
      });
      void queryClient.prefetchQuery({
        queryKey: qk.runs.transcript(id, "conversation"),
        queryFn: () =>
          apiClient.get<RunTranscript>(`/runs/${id}/transcript`, {
            params: { scope: "conversation" },
          }),
      });
    }
  }, [key, queryClient]);
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
export function useRunTranscript(
  runId: string,
  scope: "run" | "conversation" = "run",
  options?: { enabled?: boolean; refetchInterval?: number | false },
) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.runs.transcript(runId, scope),
    queryFn: () =>
      apiClient.get<RunTranscript>(
        `/runs/${runId}/transcript`,
        scope === "run" ? undefined : { params: { scope } },
      ),
    // A trigger's run-log opens on `last_run_id`, which is null until the first
    // fire - there is nothing to read until then, so the caller opts out.
    enabled: options?.enabled ?? true,
    // Set while a fire is in flight, so the just-appended reply is picked up
    // without a reload; left off otherwise, a transcript being an immutable record.
    refetchInterval: options?.refetchInterval ?? false,
    // Held across a step for the reason `useRun` holds its row, and it matters
    // more here: read `scope=conversation`, two runs of one thread answer with
    // the *same* turns, so dropping the timeline to a skeleton between them
    // rebuilds a list that was already correct. `data.run_id` says which run
    // the answer being held is anchored on.
    placeholderData: keepPreviousData,
  });
  return { transcript: data, isLoading, error };
}

/**
 * What one run handed its model - the prompt, the tools, the request waterfall.
 *
 * `error` is returned and it carries a meaning: the endpoint answers 404 for a
 * run that recorded nothing, which is a fact about that run - it never reached a
 * model, or it ran before this was recorded - and not a failed request. A
 * surface that drew both as an empty panel would say the agent was given no
 * prompt and no tools, which is a claim about the agent.
 *
 * Never refetched on its own: a manifest is written once when the run ends and
 * cannot change afterwards, so the app-wide cache is exactly right for it.
 */
export function useRunManifest(runId: string, options?: { enabled?: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.runs.manifest(runId),
    queryFn: () => apiClient.get<RunManifest>(`/runs/${runId}/manifest`),
    enabled: options?.enabled ?? true,
    // A 404 here is an answer, not a hiccup. Retrying it three times delays the
    // panel that says so by as many round trips.
    retry: false,
  });
  return { manifest: data, isLoading, error };
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
  const t = useTranslations("pages.runs");
  const tErrors = useTranslations("errors");

  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.approvals(),
    queryFn: () => apiClient.get<ApprovalList>("/approvals"),
    refetchInterval: 30_000,
    enabled: options?.enabled ?? true,
  });

  const resume = useResumeRun({ ignoreStillParked: true });

  const decide = useMutation({
    mutationFn: ({ id, approved, note }: { id: string; approved: boolean; note?: string }) =>
      apiClient.post<ToolApproval>(`/approvals/${id}`, { approved, note }),
    onSuccess: async (approval) => {
      // The invalidation refetches the queue, so the read below is fresh.
      await queryClient.invalidateQueries({ queryKey: qk.runs.all() });
      toast.success(approval.status === "approved" ? t("decisionApproved") : t("decisionRejected"));
      // Deciding the last outstanding call makes the resume possible; nothing
      // performs it (the backend keeps the click and the execution apart). The
      // chat's dialog has always followed its decision with the resume - the
      // queue not doing the same left a run approved and parked forever.
      // This read is one cached page of fifty, so a run whose other parked call
      // sits past those fifty reads as clear; `/approvals` cannot narrow by run,
      // so the backend's refusal is the real check and the auto path swallows
      // exactly that refusal (see `useResumeRun`).
      const stillParked = queryClient
        .getQueryData<ApprovalList>(qk.runs.approvals())
        ?.items.some((item) => item.run_id === approval.run_id && item.status === "pending");
      if (!stillParked) resume.mutate(approval.run_id);
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
 * The resume refusal that means another call on the run still awaits a decision.
 *
 * `POST /runs/{id}/resume` answers it as a 400 whose details name the pending
 * approval ids - the only resume refusal carrying `pending`, which keeps a spec
 * that can no longer be built, or a run that is not parked at all, toasting
 * like any other failure.
 */
function stillAwaitingDecision(error: unknown): boolean {
  return error instanceof ApiError && error.status === 400 && Array.isArray(error.details?.pending);
}

/**
 * Continue a run whose parked tool calls have all been decided.
 *
 * A decision is a click; continuing the run executes an agent - the backend
 * keeps the two apart on purpose, and the chat's approval dialog has always
 * called both. The approvals queue did not, which is how a run approved from
 * the Activity page stayed `awaiting_approval` forever: approved, undisputed,
 * and never picked back up.
 *
 * `ignoreStillParked` is for the queue's automatic resume after a decision. The
 * "anything still pending?" check it makes first reads one cached page of
 * fifty, so a run whose other parked call sits past those fifty reads as clear
 * and the resume is attempted anyway; the backend's still-parked refusal is
 * that check's answer arriving late, not news for the person who just decided.
 * Every other failure still toasts, and a resume somebody clicked never passes
 * this flag.
 */
export function useResumeRun(options?: { ignoreStillParked?: boolean }) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.runs");
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => apiClient.post<ResumedRun>(`/runs/${runId}/resume`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.runs.all() });
      toast.success(t("runResumed"));
    },
    onError: (error) => {
      if (options?.ignoreStillParked && stillAwaitingDecision(error)) return;
      toast.error(getErrorMessage(error, tErrors, t("resumeFailed")));
    },
  });
}

/**
 * The record of decided approvals over a window - the queue's counterpart.
 *
 * Newest first, because a record is read backwards from now, where the queue
 * drains oldest-first. Its own query and key: a decision must refresh the
 * queue at once, while the record only moves with the window.
 */
export function useApprovalHistory(
  range: { from: string; to: string },
  options?: { enabled?: boolean },
) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.runs.approvalHistory(range.from, range.to),
    queryFn: () =>
      apiClient.get<ApprovalList>("/approvals", {
        // Pairs, because `status` repeats - everything except the queue.
        params: [
          ["status", "approved"],
          ["status", "rejected"],
          ["status", "expired"],
          ["created_from", range.from],
          ["created_to", range.to],
          ["oldest_first", "false"],
        ],
      }),
    enabled: options?.enabled ?? true,
  });
  return { approvals: data?.items ?? [], total: data?.total ?? 0, isLoading, error };
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
 *
 * `enabled` is how a caller without `runs:view` opts out, the same bargain
 * `useApprovals` strikes: the route refuses that caller, so asking is a 403
 * whose empty rendering would read as nothing spent.
 */
export function useSpend(
  range: number | { from: string; to: string } = 30,
  options?: { enabled?: boolean },
) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.runs.spend(range),
    queryFn: () =>
      apiClient.get<CostSummary>("/spend", {
        params:
          typeof range === "number" ? { days: String(range) } : { from: range.from, to: range.to },
      }),
    enabled: options?.enabled ?? true,
    ...DASHBOARD_FRESHNESS,
  });
  return { spend: data, isLoading, error, refetch };
}
