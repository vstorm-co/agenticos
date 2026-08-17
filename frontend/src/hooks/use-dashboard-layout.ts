"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteLayout, getLayout, putLayout, type StoredLayout } from "@/lib/dashboard-layout-api";
import type { StoredEntry } from "@/lib/dashboard/preference";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

interface UseDashboardLayoutResult {
  /** The saved arrangement, or `null` when none is saved (use the default). */
  storedEntries: StoredEntry[] | null;
  isLoading: boolean;
  save: (entries: StoredEntry[]) => Promise<void>;
  reset: () => Promise<void>;
}

/**
 * The caller's saved dashboard arrangement for the active organization.
 *
 * `null` means no preference, which the page turns into the audience default -
 * distinct from an empty arrangement (`[]`), which is a person who has hidden
 * every card. Both mutations write the query cache directly, so the page
 * re-renders from the new arrangement without a refetch round-trip.
 */
export function useDashboardLayout(): UseDashboardLayoutResult {
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const queryKey = qk.dashboard.layout(activeOrgId ?? "current");

  const { data, isLoading } = useQuery({ queryKey, queryFn: getLayout });

  const saveMutation = useMutation({
    // Snapshot the key when the mutation starts, not when onSuccess runs: save,
    // then switch organization before the PUT resolves, and reading `queryKey`
    // in onSuccess would write org A's layout under org B's key.
    mutationFn: async (entries: StoredEntry[]) => ({
      key: queryKey,
      layout: await putLayout(entries),
    }),
    onSuccess: ({ key, layout }) => queryClient.setQueryData<StoredLayout | null>(key, layout),
  });

  const resetMutation = useMutation({
    // Snapshot the key at mutate time, same as the save above: reset, then switch
    // organization before the DELETE resolves, and reading `queryKey` in onSuccess
    // would write null under org B's key, dropping org B's saved arrangement.
    mutationFn: async () => {
      const key = queryKey;
      await deleteLayout();
      return key;
    },
    onSuccess: (key) => queryClient.setQueryData<StoredLayout | null>(key, null),
  });

  const save = useCallback(
    async (entries: StoredEntry[]) => {
      await saveMutation.mutateAsync(entries);
    },
    [saveMutation],
  );

  const reset = useCallback(async () => {
    await resetMutation.mutateAsync();
  }, [resetMutation]);

  return {
    storedEntries: data ? data.entries : null,
    isLoading,
    save,
    reset,
  };
}
