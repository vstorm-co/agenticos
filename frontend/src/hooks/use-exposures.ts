"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import type { Exposure, ExposureList, ExposureTarget, ExposureTargetList } from "@/types/exposures";

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

  const expose = useMutation({
    mutationFn: (channelBotId: string) =>
      apiClient.post<Exposure>(base, { channel_bot_id: channelBotId }),
    onSuccess: async (exposure) => {
      await invalidate();
      toast.success(`Now available on ${exposure.channel_bot_name}`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const setActive = useMutation({
    mutationFn: ({ exposureId, isActive }: { exposureId: string; isActive: boolean }) =>
      // Only `is_active`. The server applies exactly the fields it was sent, so
      // sending more here - even values just read back - would let a pause
      // overwrite an environment somebody rebound in between.
      apiClient.patch<Exposure>(`${base}/${exposureId}`, { is_active: isActive }),
    onSuccess: async (exposure) => {
      await invalidate();
      toast.success(
        exposure.is_active
          ? `Answering again on ${exposure.channel_bot_name}`
          : `Paused on ${exposure.channel_bot_name}`,
      );
    },
    onError: (error) => toast.error(getErrorMessage(error)),
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
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const setPrompt = useMutation({
    mutationFn: ({ exposureId, prompt }: { exposureId: string; prompt: string | null }) =>
      // Only this field goes, for the reason `setActive` says: the server
      // applies what it was sent, so reading a value back and returning it would
      // overwrite whatever somebody changed in between.
      apiClient.patch<Exposure>(`${base}/${exposureId}`, { prompt }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const revoke = useMutation({
    mutationFn: (exposureId: string) => apiClient.delete<void>(`${base}/${exposureId}`),
    onSuccess: async () => {
      await invalidate();
      toast.success("No longer available there");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
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
    revoke,
  };
}
