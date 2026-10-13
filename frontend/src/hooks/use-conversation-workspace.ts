"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  readConversationWorkspace,
  type ConversationWorkspace,
} from "@/lib/conversation-workspace-api";

interface UseConversationWorkspaceResult {
  workspace: ConversationWorkspace | null;
  isLoading: boolean;
  error: string | null;
  /** Re-read after a turn, because a turn is what changes the files. */
  refresh: () => Promise<void>;
}

/**
 * The files this conversation's agent is keeping.
 *
 * Not polled. A workspace changes when a turn runs, and the chat knows exactly
 * when that happened - so the panel is refreshed by the turn finishing rather
 * than by a timer that is wrong most of the time it fires.
 */
export function useConversationWorkspace(
  conversationId: string | null,
): UseConversationWorkspaceResult {
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const {
    data: workspace = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.conversationWorkspace.files(conversationId ?? "none"),
    queryFn: () => readConversationWorkspace(conversationId as string),
    enabled: conversationId !== null,
    retry: false,
  });

  const refresh = useCallback(async () => {
    if (conversationId === null) return;
    await queryClient.invalidateQueries({
      queryKey: qk.conversationWorkspace.files(conversationId),
    });
  }, [queryClient, conversationId]);

  return {
    workspace,
    isLoading: conversationId !== null && isLoading,
    error: error ? getErrorMessage(error, tErrors) : null,
    refresh,
  };
}

// Reading one of these files - as text, as bytes, or onto the caller's disk - is
// `use-workspace-file.ts`, which takes a source naming this conversation. One
// implementation, because the viewer it feeds is shared with the Workspaces screen
// and a file has to mean the same thing in both.
