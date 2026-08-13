"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import type { Embed, EmbedEdit, EmbedList, NewEmbed } from "@/types/embeds";

/**
 * The widgets one agent is published as.
 *
 * Mutations invalidate rather than patch the cache: the server mints the public
 * key and assembles the snippet from the deployment's own URL, and a client
 * that guessed either would show somebody a script tag that does not work.
 */
export function useEmbeds(agentId: string | null) {
  const t = useTranslations("agents");
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: qk.embeds.list(agentId ?? ""),
    queryFn: () => apiClient.get<EmbedList>(`/agents/${agentId}/embeds`),
    enabled: !!agentId,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.embeds.list(agentId ?? "") }),
    [queryClient, agentId],
  );

  const create = useMutation({
    mutationFn: (embed: NewEmbed) => apiClient.post<Embed>("/agents/embeds", embed),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("widgetPublished"));
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const update = useMutation({
    mutationFn: ({ id, ...changes }: { id: string } & EmbedEdit) =>
      apiClient.patch<Embed>(`/agents/embeds/${id}`, changes),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("widgetSaved"));
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const uploadLogo = useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) =>
      apiClient.upload<Embed>(`/agents/embeds/${id}/logo`, file),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("logoUploaded"));
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/agents/embeds/${id}`),
    onSuccess: async () => {
      await invalidate();
      // Said plainly: this is the one action here that breaks a live page.
      toast.success(t("widgetRemoved"));
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return { uploadLogo, embeds: data?.items ?? [], isLoading, create, update, remove };
}
