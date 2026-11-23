"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getNavPins, putNavPins, type NavPins } from "@/lib/nav-pins-api";
import { toggledPins } from "@/lib/nav-pins";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

interface UseNavPinsResult {
  /** The saved ids in pinned order; empty until read, and for anyone who pinned nothing. */
  pinnedIds: string[];
  /** Pin the item, or unpin it when already pinned. */
  toggle: (id: string) => void;
}

/**
 * The caller's pinned sidebar items for the active organization.
 *
 * A toggle writes the cache first and rolls back if the save fails, so the
 * column answers the click where it was made. The key is snapshotted when the
 * toggle starts: switching organization before the PUT resolves must not write
 * one organization's pins under another's key.
 */
export function useNavPins(): UseNavPinsResult {
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const queryKey = qk.nav.pins(activeOrgId ?? "current");

  const { data } = useQuery({ queryKey, queryFn: getNavPins });

  const save = useMutation({
    mutationFn: async ({
      key,
      ids,
    }: {
      key: readonly string[];
      ids: string[];
      previous?: NavPins;
    }) => ({
      key,
      saved: await putNavPins(ids),
    }),
    onMutate: ({ key, ids }) => {
      queryClient.setQueryData<NavPins>(key, { item_ids: ids });
    },
    onError: (_error, { key, previous }) =>
      queryClient.setQueryData<NavPins | undefined>(key, previous),
    onSuccess: ({ key, saved }) => queryClient.setQueryData<NavPins>(key, saved),
  });

  const toggle = useCallback(
    (id: string) => {
      const previous = queryClient.getQueryData<NavPins>(queryKey);
      save.mutate({ key: queryKey, ids: toggledPins(previous?.item_ids ?? [], id), previous });
    },
    [queryClient, queryKey, save],
  );

  return { pinnedIds: data?.item_ids ?? [], toggle };
}
