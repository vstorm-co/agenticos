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
  /** True once the saved list has loaded; pin controls stay disabled before that. */
  ready: boolean;
  /** Pin the item, or unpin it when already pinned. Does nothing before `ready`. */
  toggle: (id: string) => void;
}

/**
 * What the server last confirmed, and the newest click, per organization key.
 * Module-level because the desktop column and the mobile slide-over each mount
 * this hook, and a save started in one must be judged against clicks in both.
 */
const confirmed = new Map<string, string[]>();
const latestClick = new Map<string, number>();
let clicks = 0;

interface SaveRequest {
  key: ReturnType<typeof qk.nav.pins>;
  id: string;
  click: number;
}

/**
 * The caller's pinned sidebar items for the active organization.
 *
 * A click is shown at once and then saved; saves for one organization run one
 * at a time (a mutation scope), and each computes its list from what the server
 * last confirmed when it actually runs, so a failed earlier save cannot leak
 * into a later one. Only the newest click may write the result back or roll
 * the column back: a late answer to an older click never overwrites a newer one.
 * The key is snapshotted at click time, so switching organization mid-save
 * cannot write one organization's pins under another's key.
 */
export function useNavPins(): UseNavPinsResult {
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const queryKey = qk.nav.pins(activeOrgId ?? "current");
  const scopeId = queryKey.join(":");

  const { data } = useQuery({
    queryKey,
    queryFn: async () => {
      const read = await getNavPins();
      confirmed.set(scopeId, read.item_ids);
      return read;
    },
  });

  const save = useMutation({
    scope: { id: scopeId },
    mutationFn: async ({ key, id }: SaveRequest) => {
      const saved = await putNavPins(toggledPins(confirmed.get(key.join(":")) ?? [], id));
      confirmed.set(key.join(":"), saved.item_ids);
      return saved;
    },
    onMutate: async ({ key, id }) => {
      await queryClient.cancelQueries({ queryKey: key });
      const shown = queryClient.getQueryData<NavPins>(key)?.item_ids ?? [];
      queryClient.setQueryData<NavPins>(key, { item_ids: toggledPins(shown, id) });
    },
    onError: (_error, { key, click }) => {
      if (latestClick.get(key.join(":")) !== click) return;
      queryClient.setQueryData<NavPins>(key, { item_ids: confirmed.get(key.join(":")) ?? [] });
    },
    onSuccess: (saved, { key, click }) => {
      if (latestClick.get(key.join(":")) !== click) return;
      queryClient.setQueryData<NavPins>(key, saved);
    },
  });

  const ready = data !== undefined;
  const toggle = useCallback(
    (id: string) => {
      if (!ready) return;
      clicks += 1;
      latestClick.set(scopeId, clicks);
      save.mutate({ key: queryKey, id, click: clicks });
    },
    [ready, save, scopeId, queryKey],
  );

  return { pinnedIds: data?.item_ids ?? [], ready, toggle };
}
