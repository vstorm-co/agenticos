"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
      toast.success("Widget published. Copy the snippet into your site.");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const update = useMutation({
    mutationFn: ({ id, ...changes }: { id: string } & EmbedEdit) =>
      apiClient.patch<Embed>(`/agents/embeds/${id}`, changes),
    onSuccess: async () => {
      await invalidate();
      toast.success("Saved");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/agents/embeds/${id}`),
    onSuccess: async () => {
      await invalidate();
      // Said plainly: this is the one action here that breaks a live page.
      toast.success("Widget removed. Every page carrying its key has stopped working.");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return { embeds: data?.items ?? [], isLoading, create, update, remove };
}
