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
  TriggerActivationStatus,
  TriggerAttemptList,
  TriggerFilteredEventRead,
  TriggerCreate,
  TriggerCreated,
  TriggerDispatch,
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

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.triggers.list(agentId ?? ""),
    queryFn: () => apiClient.get<TriggerList>(base),
    enabled: !!agentId,
    refetchInterval: (query) =>
      query.state.data?.items.some((trigger) => trigger.is_active && trigger.local_target != null)
        ? 30_000
        : false,
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
      await Promise.all([
        invalidate(),
        queryClient.invalidateQueries({ queryKey: qk.conversations.all() }),
      ]);
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
    mutationFn: (triggerId: string) =>
      apiClient.post<TriggerDispatch>(`${base}/${triggerId}/run`, {}),
    onSuccess: async () => {
      await Promise.all([invalidate(), queryClient.invalidateQueries({ queryKey: qk.runs.all() })]);
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

  const rotateSecret = useMutation({
    // `TriggerCreated` for the same reason `create` is: the response carries the
    // new signing secret in `reveal_secret`, shown exactly once, which no read
    // ever returns. It is null for an auto-webhook trigger the platform re-armed
    // itself, and the new secret to paste for a manual one.
    mutationFn: (triggerId: string) =>
      apiClient.post<TriggerCreated>(`${base}/${triggerId}/rotate-secret`, {}),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("secretRotated"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    triggers: data?.items ?? [],
    isLoading,
    error,
    refetch,
    create,
    update,
    setActive,
    runNow,
    remove,
    rotateSecret,
  };
}

/** Durable refusals are separate from agent runs and survive notification delivery failures. */
export function useTriggerAttempts(trigger: Trigger, page: number, pending: boolean) {
  return useQuery({
    queryKey: qk.triggers.attempts(trigger.agent_id, trigger.id, page),
    queryFn: () =>
      apiClient.get<TriggerAttemptList>(
        `/agents/${trigger.agent_id}/triggers/${trigger.id}/attempts?skip=${page * 10}&limit=10`,
      ),
    refetchInterval: pending ? 3000 : trigger.is_active ? 30_000 : false,
  });
}

/** One accepted activation, independent of the history pages currently displayed. */
export function useTriggerActivation(
  trigger: Trigger,
  activationId: string | null,
  jobId: string | null,
  enabled: boolean,
) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: qk.triggers.activation(trigger.agent_id, trigger.id, activationId ?? "", jobId),
    enabled: enabled && activationId !== null,
    queryFn: async () => {
      const status = await apiClient.get<TriggerActivationStatus>(
        `/agents/${trigger.agent_id}/triggers/${trigger.id}/activations/${activationId}`,
        jobId === null ? undefined : { params: { job_id: jobId } },
      );
      if (status.state !== "pending") {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: qk.runs.all() }),
          queryClient.invalidateQueries({
            queryKey: qk.triggers.attempts(trigger.agent_id, trigger.id, 0),
            exact: true,
          }),
          queryClient.invalidateQueries({
            queryKey: qk.triggers.list(trigger.agent_id),
            exact: true,
          }),
          queryClient.invalidateQueries({ queryKey: qk.triggers.orgList(), exact: true }),
        ]);
      }
      return status;
    },
    refetchInterval: (query) =>
      query.state.error === null && query.state.data?.state === "pending" ? 3000 : false,
  });
}

/** Owner-only metadata; no request is made for other viewers of the agent. */
export function useTriggerFilteredEvent(trigger: Trigger, enabled: boolean) {
  return useQuery({
    queryKey: qk.triggers.filteredEvent(trigger.agent_id, trigger.id),
    queryFn: () =>
      apiClient.get<TriggerFilteredEventRead>(
        `/agents/${trigger.agent_id}/triggers/${trigger.id}/filtered-event`,
      ),
    enabled,
    refetchInterval: 30_000,
  });
}
