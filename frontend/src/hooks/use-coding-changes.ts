"use client";

import {
  queryOptions,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect } from "react";

import { ApiError } from "@/lib/api-error";
import {
  readCodingChanges,
  revertCodingChanges,
  type CodingTaskChanges,
} from "@/lib/coding-changes-api";
import { qk } from "@/lib/query-keys";

interface UseCodingChangesResult {
  changes: CodingTaskChanges | null;
  isLoading: boolean;
  failed: boolean;
}

/**
 * What one coding task changed, for the panel under it.
 *
 * The files are fixed, but revert state and the reader's access can change. A refusal is
 * not retried - a 404 means the reader may not see it, and asking again will
 * not change that - but a 5xx or a dropped connection keeps the client's single
 * retry, or the panel would stay empty after the server recovers.
 */
function codingChangesQuery(changeId: string) {
  return queryOptions({
    queryKey: qk.codingChanges.detail(changeId),
    queryFn: () => readCodingChanges(changeId),
    refetchInterval: (query) => (query.state.data?.revert_status === "pending" ? 1000 : false),
    retry: (failureCount: number, cause: Error) =>
      !(cause instanceof ApiError && cause.status < 500) && failureCount < 1,
  });
}

export function useCodingChanges(changeId: string): UseCodingChangesResult {
  const { data, isLoading, isError } = useQuery(codingChangesQuery(changeId));
  useRefreshRevertedFiles(data?.reverted_at ?? "");
  return { changes: data ?? null, isLoading, failed: isError };
}

function useRefreshRevertedFiles(stamp: string) {
  const client = useQueryClient();
  useEffect(() => {
    if (!stamp) return;
    void client.invalidateQueries({ queryKey: qk.conversationWorkspace.all() });
    void client.invalidateQueries({ queryKey: qk.sandboxWorkspaces.all() });
    void client.invalidateQueries({ queryKey: qk.projects.all() });
  }, [client, stamp]);
}

export function useCodingChangeSets(changeIds: string[]): Map<string, CodingTaskChanges> {
  const queries = useQueries({ queries: changeIds.map(codingChangesQuery) });
  useRefreshRevertedFiles(queries.map(({ data }) => data?.reverted_at ?? "").join(""));
  return new Map(queries.flatMap(({ data }) => (data ? [[data.id, data] as const] : [])));
}

export function useRevertCodingChanges() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: revertCodingChanges,
    retry: false,
    onSuccess: (changes) => {
      client.setQueryData(qk.codingChanges.detail(changes.id), changes);
      void client.invalidateQueries({ queryKey: qk.conversationWorkspace.all() });
      void client.invalidateQueries({ queryKey: qk.sandboxWorkspaces.all() });
      void client.invalidateQueries({ queryKey: qk.projects.all() });
    },
  });
}
