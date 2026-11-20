"use client";

import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  appearanceGeneration,
  adoptAccountAppearance,
  isCurrentAppearanceOwner,
} from "@/lib/account-appearance";
import {
  getUserAppearance,
  saveUserAppearance,
  resetUserAppearance,
} from "@/lib/user-appearance-api";
import type { UserAppearance } from "@/lib/user-appearance";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

type Change = ({ kind: "save"; preferences: Partial<UserAppearance> } | { kind: "reset" }) & {
  epoch: number;
};

/** Account keys survive an organization switch, and never cross account identity. */
export function useUserAppearance() {
  const owner = useAuthStore((state) => state.user?.id);
  const client = useQueryClient();
  const key = qk.auth.appearance(owner);
  const query = useQuery({
    queryKey: key,
    enabled: !!owner,
    staleTime: 15_000,
    refetchInterval: 30_000,
    queryFn: async ({ signal }) => {
      const epoch = appearanceGeneration();
      const preferences = await getUserAppearance(signal);
      return { owner, epoch, preferences };
    },
  });
  const mutation = useMutation({
    mutationKey: key,
    scope: { id: `appearance:${owner}` },
    mutationFn: async (change: Change) => {
      const { epoch } = change;
      await client.cancelQueries({ queryKey: key });
      if (!owner || !isCurrentAppearanceOwner(owner, epoch)) {
        // i18n-exempt: internal cancellation; a changed account unmounts the editor.
        throw new Error("Appearance session changed");
      }
      const preferences =
        change.kind === "reset"
          ? await resetUserAppearance()
          : await saveUserAppearance(change.preferences);
      return { owner, epoch, preferences };
    },
    onSuccess: (saved) => {
      if (adoptAccountAppearance(saved.owner, saved.epoch, saved.preferences)) {
        client.setQueryData(qk.auth.appearance(saved.owner), saved);
      }
    },
  });
  const pending = useIsMutating({ mutationKey: key }) > 0;
  const data = query.data;
  return {
    owner,
    preferences:
      data && data.owner === owner && data.epoch === appearanceGeneration()
        ? data.preferences
        : undefined,
    epoch: data?.epoch,
    isLoading: query.isLoading,
    error: query.error,
    pending,
    refetch: query.refetch,
    save: (preferences: Partial<UserAppearance>) =>
      mutation.mutateAsync({ kind: "save", preferences, epoch: appearanceGeneration() }),
    reset: () => mutation.mutateAsync({ kind: "reset", epoch: appearanceGeneration() }),
  };
}
