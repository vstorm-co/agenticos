"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { qk } from "@/lib/query-keys";
import {
  readConversationFile,
  readConversationWorkspace,
  type ConversationFileContent,
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
    error: error === null ? null : error.message,
    refresh,
  };
}

interface UseConversationFileResult {
  file: ConversationFileContent | null;
  isLoading: boolean;
  error: string | null;
}

/** One file's text, fetched when somebody opens it and not before. */
export function useConversationFile(
  conversationId: string | null,
  path: string | null,
): UseConversationFileResult {
  const {
    data: file = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.conversationWorkspace.file(conversationId ?? "none", path ?? "none"),
    queryFn: () => readConversationFile(conversationId as string, path as string),
    enabled: conversationId !== null && path !== null,
    retry: false,
  });

  return {
    file,
    isLoading: conversationId !== null && path !== null && isLoading,
    error: error === null ? null : error.message,
  };
}
