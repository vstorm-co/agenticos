"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import type {
  ChannelBot,
  ChannelBotCreate,
  ChannelBotList,
  UsageReporting,
} from "@/types/channels";

/**
 * The organization's channel bots - what the Builder's "where is this agent
 * available" section binds agents to.
 *
 * Listing requires `channels:manage`, so callers gate on that permission and
 * this hook does not fetch until told the caller holds it - a 403 in the
 * network log for every member visiting the org page would read as a bug.
 */
export function useChannelBots(enabled: boolean) {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: qk.channelBots.list(),
    queryFn: () => apiClient.get<ChannelBotList>("/channels/bots"),
    enabled,
  });

  // Exposure targets too: this panel renders beside the exposures picker, and
  // a bot registered there must be offerable without a page reload.
  const invalidate = useCallback(
    () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.channelBots.list() }),
        queryClient.invalidateQueries({ queryKey: qk.exposures.all() }),
      ]),
    [queryClient],
  );

  const create = useMutation({
    mutationFn: (bot: ChannelBotCreate) => apiClient.post<ChannelBot>("/channels/bots", bot),
    onSuccess: async (bot) => {
      await invalidate();
      toast.success(`${bot.name} registered - agents can now be exposed on it`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const setActive = useMutation({
    mutationFn: ({ botId, isActive }: { botId: string; isActive: boolean }) =>
      apiClient.post<ChannelBot>(
        `/channels/bots/${botId}/${isActive ? "activate" : "deactivate"}`,
        {},
      ),
    onSuccess: async (bot) => {
      await invalidate();
      toast.success(bot.is_active ? `${bot.name} activated` : `${bot.name} deactivated`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const setUsageReporting = useMutation({
    mutationFn: ({ botId, usageReporting }: { botId: string; usageReporting: UsageReporting }) =>
      // Only this field. The server applies exactly what it was sent, so reading
      // the access policy back and returning it alongside would let a change to
      // how noisy a bot is overwrite a change to who may talk to it.
      apiClient.patch<ChannelBot>(`/channels/bots/${botId}`, {
        usage_reporting: usageReporting,
      }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const remove = useMutation({
    mutationFn: (botId: string) => apiClient.delete<void>(`/channels/bots/${botId}`),
    onSuccess: async () => {
      await invalidate();
      toast.success("Bot removed");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return { bots: data?.items ?? [], isLoading, create, setActive, setUsageReporting, remove };
}
