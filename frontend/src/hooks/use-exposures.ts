"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { UsageReporting } from "@/types/channels";
import type { Exposure, ExposureList, ExposureTarget, ExposureTargetList } from "@/types/exposures";
import type { ChannelObservationConfig } from "@/types/exposures";

/**
 * Refresh every view of a binding: each agent's bindings and targets, and the
 * channels listing that names who answers on a bot. A binding is seen from both
 * sides, so a change made on either page must reach the other.
 */
function invalidateBindings(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: qk.exposures.all() }),
    queryClient.invalidateQueries({ queryKey: qk.channelBots.list() }),
  ]);
}

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

  const { data, isLoading } = useQuery({
    queryKey: qk.exposures.list(agentId ?? ""),
    queryFn: () => apiClient.get<ExposureList>(base),
    enabled: !!agentId,
  });

  const { data: targets } = useQuery({
    queryKey: qk.exposures.targets(agentId ?? ""),
    queryFn: () => apiClient.get<ExposureTargetList>(`${base}/targets`),
    enabled: !!agentId,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.exposures.list(agentId ?? "") }),
    [queryClient, agentId],
  );
  // Bind, pause and unbind change what the channels listing shows; the PATCHes
  // above change nothing it shows, so they keep the narrower key.
  const invalidateEverywhere = useCallback(() => invalidateBindings(queryClient), [queryClient]);

  const expose = useMutation({
    mutationFn: (channelBotId: string) =>
      apiClient.post<Exposure>(base, { channel_bot_id: channelBotId }),
    onSuccess: async (exposure) => {
      await invalidateEverywhere();
      toast.success(t("exposureLive", { bot: exposure.channel_bot_name }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setActive = useMutation({
    mutationFn: ({ exposureId, isActive }: { exposureId: string; isActive: boolean }) =>
      // Only `is_active`. The server applies exactly the fields it was sent, so
      // sending more here - even values just read back - would let a pause
      // overwrite an environment somebody rebound in between.
      apiClient.patch<Exposure>(`${base}/${exposureId}`, { is_active: isActive }),
    onSuccess: async (exposure) => {
      await invalidateEverywhere();
      toast.success(
        exposure.is_active
          ? t("exposureResumed", { bot: exposure.channel_bot_name })
          : t("exposurePaused", { bot: exposure.channel_bot_name }),
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
      apiClient.patch<Exposure>(`${base}/${exposureId}`, { environment_id: environmentId }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setPrompt = useMutation({
    mutationFn: ({ exposureId, prompt }: { exposureId: string; prompt: string | null }) =>
      // Prompt and its interpretation change together; never overwrite the
      // binding's independently edited tools, environment or workspace scope.
      apiClient.patch<Exposure>(`${base}/${exposureId}`, {
        prompt,
        prompt_replaces_defaults: prompt !== null,
      }),
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

  const setObservation = useMutation({
    mutationFn: ({
      exposureId,
      observation,
    }: {
      exposureId: string;
      observation: ChannelObservationConfig;
    }) => apiClient.patch<Exposure>(`${base}/${exposureId}`, { observation }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const revoke = useMutation({
    mutationFn: (exposureId: string) => apiClient.delete<void>(`${base}/${exposureId}`),
    onSuccess: async () => {
      await invalidateEverywhere();
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
    setObservation,
    revoke,
  };
}

/**
 * Bind and unbind agents from the bot's side, on the Channels page.
 *
 * The same endpoints as `useExposures`, so the server's `agents:publish` check
 * on the agent is the only authority. A bind sends the bot alone: the binding
 * takes the agent's default environment, and the rest is set on the agent's
 * Availability tab.
 */
export function useBotBindings() {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.channels");
  const queryClient = useQueryClient();

  const bind = useMutation({
    mutationFn: ({ agentId, botId }: { agentId: string; botId: string; agentSlug: string }) =>
      apiClient.post<Exposure>(`/agents/${agentId}/exposures`, { channel_bot_id: botId }),
    onSuccess: async (exposure, { agentSlug }) => {
      await invalidateBindings(queryClient);
      toast.success(t("agentBound", { agent: agentSlug, bot: exposure.channel_bot_name }));
    },
    onError: async (error) => {
      toast.error(getErrorMessage(error, tErrors));
      // A conflict means another tab or client bound the bot, so the row the
      // dialog sits over is stale: show the binding that is really there.
      if (error instanceof ApiError && error.status === 409) {
        await queryClient.invalidateQueries({ queryKey: qk.channelBots.list() });
      }
    },
  });

  const unbind = useMutation({
    mutationFn: ({
      agentId,
      exposureId,
    }: {
      agentId: string;
      exposureId: string;
      agentSlug: string;
      botName: string;
    }) => apiClient.delete<void>(`/agents/${agentId}/exposures/${exposureId}`),
    onSuccess: async (_data, { agentSlug, botName }) => {
      await invalidateBindings(queryClient);
      toast.success(t("agentUnbound", { agent: agentSlug, bot: botName }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return { bind, unbind };
}
