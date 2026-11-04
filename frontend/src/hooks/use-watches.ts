"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  createWatch,
  deleteWatch,
  listWatchPresets,
  listWatches,
  updateWatch,
  type Watch,
  type WatchChanges,
  type WatchDraft,
  type WatchPreset,
} from "@/lib/watches-api";

/**
 * The person's watches over their own connections, and the three ways to change
 * them (#2301). Every change refetches the list, which also says why a watch that
 * is on is not being read.
 */
export function useWatches() {
  const client = useQueryClient();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.watches.mine(),
    queryFn: listWatches,
  });
  const settle = { onSettled: () => client.invalidateQueries({ queryKey: qk.watches.mine() }) };
  const create = useMutation({ mutationFn: (draft: WatchDraft) => createWatch(draft), ...settle });
  const update = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: WatchChanges }) =>
      updateWatch(id, changes),
    ...settle,
  });
  const remove = useMutation({ mutationFn: (id: string) => deleteWatch(id), ...settle });

  return {
    watches: data ?? ([] as Watch[]),
    isLoading,
    error,
    refetch,
    create: create.mutateAsync,
    update: update.mutateAsync,
    remove: remove.mutateAsync,
  };
}

/** The ready-made watches, by the catalog server each is for. They change with a deploy. */
export function useWatchPresets() {
  const { data } = useQuery({
    queryKey: qk.watches.presets(),
    queryFn: listWatchPresets,
    staleTime: Infinity,
  });
  return data ?? ([] as WatchPreset[]);
}
