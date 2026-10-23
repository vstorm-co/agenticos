"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";
import { qk } from "@/lib/query-keys";
import type {
  ChannelBot,
  ChannelBotCreate,
  ChannelBotList,
  ChannelBotUpdate,
  TeamsConversation,
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
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.channels");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
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

  // What the create mutation cannot do: a credential added after registration.
  // A Slack app hands out its `xapp-` token from a different screen than its
  // bot token, so the transport a bot needs is routinely generated after the
  // row exists - and without this the only way to supply it was to delete the
  // bot, losing the binding with it.
  const update = useMutation({
    mutationFn: ({ botId, data }: { botId: string; data: ChannelBotUpdate }) =>
      apiClient.patch<ChannelBot>(`/channels/bots/${botId}`, data),
    onSuccess: async (bot) => {
      await invalidate();
      toast.success(t("botUpdated", { bot: bot.name }));
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

  return { bots: data?.items ?? [], isLoading, error, refetch, create, update, setActive, remove };
}

/**
 * One bot as its edit form reads it, with what "inherit" would transcribe on.
 *
 * The listing leaves `inherited_speech_to_text` out - resolving it reads the
 * version of the agent the bot serves, which a page of bots should not pay for
 * - so the form asks for its one row. `null` until it answers.
 */
export function useChannelBot(botId: string | null): ChannelBot | null {
  const { data } = useQuery({
    queryKey: qk.channelBots.detail(botId ?? ""),
    queryFn: () => apiClient.get<ChannelBot>(`/channels/bots/${botId}`),
    enabled: botId !== null,
  });
  return data ?? null;
}

/**
 * Copy a Slack bot's app manifest to the clipboard (#2067).
 *
 * The manifest is the whole Slack app - its events, buttons, `/agent`, the
 * assistant pane and App Home - pointed at this deployment, so creating the app
 * in Slack is pasting it rather than filling in six screens by hand.
 */
export function useCopySlackManifest() {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.channels");
  return useMutation({
    mutationFn: async (botId: string) => {
      const manifest = await apiClient.get<Record<string, unknown>>(
        `/channels/bots/${botId}/slack-manifest`,
      );
      await navigator.clipboard.writeText(JSON.stringify(manifest, null, 2));
    },
    onSuccess: () => toast.success(t("slackManifestCopied")),
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
}

/**
 * The Teams app package for one bot (#1985): the manifest naming its Azure
 * registration and the two icons, zipped - what an administrator uploads to the
 * tenant's app catalog instead of writing a manifest by hand.
 */
export function useDownloadTeamsPackage() {
  const tErrors = useTranslations("errors");
  return useMutation({
    mutationFn: async (bot: { id: string; name: string }) => {
      const response = await apiClient.raw(`/channels/bots/${bot.id}/teams-app-package`);
      saveBlob(await response.blob(), `${bot.name.replace(/[^\w.-]+/g, "-")}-teams-app.zip`);
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
}

/** Where a trigger can post: the Teams channels and group chats the organization's bots are in. */
export function useTeamsConversations(enabled = true) {
  return useQuery({
    queryKey: qk.channelBots.teamsConversations(),
    queryFn: async () =>
      (await apiClient.get<{ items: TeamsConversation[] }>("/channels/teams-conversations")).items,
    enabled,
  });
}
