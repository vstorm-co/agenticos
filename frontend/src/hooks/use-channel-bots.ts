"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { ChannelBot, ChannelBotCreate, ChannelBotList } from "@/types/channels";

/**
 * The organization's channel bots - what the Builder's "where is this agent
 * available" section binds agents to.
 *
 * Listing requires `channels:manage`, so callers gate on that permission and
 * this hook does not fetch until told the caller holds it - a 403 in the
 * network log for every member visiting the org page would read as a bug.
 */
export function useChannelBots(enabled: boolean) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.channels");
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
      toast.success(t("botRegistered", { bot: bot.name }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setActive = useMutation({
    mutationFn: ({ botId, isActive }: { botId: string; isActive: boolean }) =>
      apiClient.post<ChannelBot>(
        `/channels/bots/${botId}/${isActive ? "activate" : "deactivate"}`,
        {},
      ),
    onSuccess: async (bot) => {
      await invalidate();
      toast.success(
        bot.is_active
          ? t("botActivated", { bot: bot.name })
          : t("botDeactivated", { bot: bot.name }),
      );
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const remove = useMutation({
    mutationFn: (botId: string) => apiClient.delete<void>(`/channels/bots/${botId}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("botRemoved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return { bots: data?.items ?? [], isLoading, create, setActive, remove };
}
