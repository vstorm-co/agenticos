"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { DeferredBinding, UsageReporting } from "@/types/channels";
import type { Exposure, ExposureList, ExposureTarget, ExposureTargetList } from "@/types/exposures";

const isDeferred = (answer: Exposure | DeferredBinding): answer is DeferredBinding =>
  "request_id" in answer;

/**
 * Where one agent is available, and where it could be.
 *
 * Two queries rather than one: the bindings change every time somebody edits
 * this section, while the list of bots an organization has changes almost never
 * - merging them would re-fetch the second every time the first moved.
 *
 * Mutations invalidate rather than patch, for the reason sharing does: the
 * server resolves a bot's name into the row it returns, and a client that
 * guessed it would render a place that does not exist.
 */
export function useExposures(agentId: string | null) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("agents");
  const queryClient = useQueryClient();
  const base = `/agents/${agentId}/exposures`;
  const id = agentId ?? "";

  const { data, isLoading } = useQuery({
    queryKey: qk.exposures.list(id),
    queryFn: () => apiClient.get<ExposureList>(base),
    enabled: !!agentId,
  });

  const { data: targets } = useQuery({
    queryKey: qk.exposures.targets(id),
    queryFn: () => apiClient.get<ExposureTargetList>(`${base}/targets`),
    enabled: !!agentId,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.exposures.list(id) }),
    [queryClient, id],
  );

  // A change on a public line may wait for an administrator: the server answers
  // 202 with the request instead of the binding, and nothing is live to re-read.
  const requested = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: qk.exposures.requests(id) });
    toast.success(t("bindingRequested"));
  }, [queryClient, id, t]);

  const expose = useMutation({
    mutationFn: ({ channelBotId, requestNote }: { channelBotId: string; requestNote?: string }) =>
      apiClient.post<Exposure | DeferredBinding>(base, {
        channel_bot_id: channelBotId,
        ...(requestNote ? { request_note: requestNote } : {}),
      }),
    onSuccess: async (answer) => {
      if (isDeferred(answer)) return requested();
      await invalidate();
      toast.success(t("exposureLive", { bot: answer.channel_bot_name }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setActive = useMutation({
    mutationFn: ({ exposureId, isActive }: { exposureId: string; isActive: boolean }) =>
      // Only `is_active`. The server applies exactly the fields it was sent, so
      // sending more here - even values just read back - would let a pause
      // overwrite an environment somebody rebound in between.
      apiClient.patch<Exposure | DeferredBinding>(`${base}/${exposureId}`, {
        is_active: isActive,
      }),
    onSuccess: async (answer) => {
      if (isDeferred(answer)) return requested();
      await invalidate();
      toast.success(
        answer.is_active
          ? t("exposureResumed", { bot: answer.channel_bot_name })
          : t("exposurePaused", { bot: answer.channel_bot_name }),
      );
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setEnvironment = useMutation({
    mutationFn: ({
      exposureId,
      environmentId,
    }: {
      exposureId: string;
      environmentId: string | null;
    }) =>
      // Explicit null returns the binding to the default environment - the
      // server reads the distinction off the request, so only this field goes.
      apiClient.patch<Exposure | DeferredBinding>(`${base}/${exposureId}`, {
        environment_id: environmentId,
      }),
    onSuccess: async (answer) => {
      if (isDeferred(answer)) return requested();
      await invalidate();
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setPrompt = useMutation({
    mutationFn: ({ exposureId, prompt }: { exposureId: string; prompt: string | null }) =>
      // Only this field goes, for the reason `setActive` says: the server
      // applies what it was sent, so reading a value back and returning it would
      // overwrite whatever somebody changed in between.
      apiClient.patch<Exposure>(`${base}/${exposureId}`, { prompt }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setTools = useMutation({
    mutationFn: ({ exposureId, tools }: { exposureId: string; tools: string[] }) =>
      // Only this field, for the reason `setActive` says. The whole list rather
      // than the box that moved: the server stores what a binding grants, and a
      // patch describing one checkbox could not express "and nothing else".
      apiClient.patch<Exposure>(`${base}/${exposureId}`, { tools }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setUsageReporting = useMutation({
    mutationFn: ({
      exposureId,
      usageReporting,
    }: {
      exposureId: string;
      usageReporting: UsageReporting;
    }) =>
      // Only this field, for the reason `setActive` says: the server applies
      // what it was sent, so reading a value back and returning it alongside
      // would overwrite whatever somebody changed in between.
      apiClient.patch<Exposure>(`${base}/${exposureId}`, { usage_reporting: usageReporting }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const revoke = useMutation({
    mutationFn: (exposureId: string) => apiClient.delete<void>(`${base}/${exposureId}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("exposureRevoked"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const exposures: Exposure[] = data?.items ?? [];
  const boundBotIds = new Set(exposures.map((exposure) => exposure.channel_bot_id));

  return {
    exposures,
    isLoading,
    /**
     * Bots this agent is not already on. An agent binds to a bot at most once,
     * so offering a bot it already answers on would only produce a refusal the
     * person could have been spared.
     */
    available: (targets?.items ?? []).filter(
      (target: ExposureTarget) => !boundBotIds.has(target.id),
    ),
    expose,
    setActive,
    setEnvironment,
    setPrompt,
    setTools,
    setUsageReporting,
    revoke,
  };
}
