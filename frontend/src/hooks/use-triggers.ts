"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/api-error";
import type {
  Trigger,
  TriggerCreate,
  TriggerCreated,
  TriggerList,
  TriggerUpdate,
} from "@/types/triggers";

/**
 * One agent's schedules and event triggers, and the writes that change them.
 *
 * Mutations invalidate rather than patch, for the reason exposures does: the
 * server resolves and derives fields on the row it returns - the run-log
 * conversation it opens eagerly, the webhook path it computes - and a client that
 * guessed them would render state that does not exist. Invalidation reaches
 * `qk.triggers.all()` so the org-wide surfaces (the sidebar section, the Activity
 * tab) refetch too: a trigger created here is a row they also show.
 */
export function useTriggers(agentId: string | null) {
  const queryClient = useQueryClient();
  const t = useTranslations("triggers");
  const tErrors = useTranslations("errors");
  const base = `/agents/${agentId}/triggers`;

  const { data, isLoading } = useQuery({
    queryKey: qk.triggers.list(agentId ?? ""),
    queryFn: () => apiClient.get<TriggerList>(base),
    enabled: !!agentId,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.triggers.all() }),
    [queryClient],
  );

  const create = useMutation({
    // `TriggerCreated` rather than `Trigger`: the create response carries the
    // reveal-once `reveal_secret` for a manual preset, which no read ever returns.
    mutationFn: (payload: TriggerCreate) => apiClient.post<TriggerCreated>(base, payload),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("created"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const update = useMutation({
    mutationFn: ({ triggerId, patch }: { triggerId: string; patch: TriggerUpdate }) =>
      apiClient.patch<Trigger>(`${base}/${triggerId}`, patch),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setActive = useMutation({
    mutationFn: ({ triggerId, isActive }: { triggerId: string; isActive: boolean }) =>
      // Only `is_active`. The server applies exactly the fields it was sent, so
      // sending more - even values read back - would let a pause overwrite an
      // environment somebody rebound in between.
      apiClient.patch<Trigger>(`${base}/${triggerId}`, { is_active: isActive }),
    onSuccess: async (trigger) => {
      await invalidate();
      toast.success(trigger.is_active ? t("resumedToast") : t("pausedToast"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const runNow = useMutation({
    mutationFn: (triggerId: string) => apiClient.post<Trigger>(`${base}/${triggerId}/run`, {}),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("runningNow"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const remove = useMutation({
    mutationFn: (triggerId: string) => apiClient.delete<void>(`${base}/${triggerId}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("removed"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    triggers: (data?.items ?? []) as Trigger[],
    isLoading,
    create,
    update,
    setActive,
    runNow,
    remove,
  };
}
