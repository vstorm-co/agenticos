"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import {
  createDiscordRoleMapping,
  deleteDiscordRoleMapping,
  listDiscordRoleMappings,
  listDiscordServers,
} from "@/lib/discord-roles-api";
import { qk } from "@/lib/query-keys";
import type { DiscordRoleMappingCreate } from "@/types/channels";

/**
 * One Discord bot's server role mappings (#2569).
 *
 * `create` reports no failure of its own, for the reason `useDirectoryMappings`
 * gives: the form shows a refused server or role under the field it came from.
 */
export function useDiscordRoleMappings(botId: string) {
  const t = useTranslations("discordRoles");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: qk.channelBots.discordRoleMappings(botId),
    queryFn: () => listDiscordRoleMappings(botId),
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.channelBots.discordRoleMappings(botId) }),
    [queryClient, botId],
  );

  const create = useMutation({
    mutationFn: (input: DiscordRoleMappingCreate) => createDiscordRoleMapping(botId, input),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("mappingAdded"));
    },
  });

  const remove = useMutation({
    mutationFn: (mappingId: string) => deleteDiscordRoleMapping(botId, mappingId),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("mappingDeleted"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  return { mappings: data?.items ?? [], isLoading, error, create, remove };
}

/**
 * The servers the bot is in and the roles a mapping may name, read live from Discord.
 *
 * Only while the add form is open: each read is a request to Discord per server.
 */
export function useDiscordServers(botId: string, enabled: boolean) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.channelBots.discordServers(botId),
    queryFn: () => listDiscordServers(botId),
    enabled,
  });
  return { servers: data?.items ?? [], isLoading, error };
}
