"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import {
  getAgentMessageThread,
  listAgentMessageRecipients,
  listAgentMessages,
  listAgentMessageThreads,
  markAgentMessageThreadRead,
  reactToAgentMessage,
  sendAgentMessage,
} from "@/lib/agent-messages-api";
import { qk } from "@/lib/query-keys";
import type { AgentMessageSend } from "@/types/agent-messages";

/**
 * The threads involving an agent this caller may run, most recently active
 * first. `total` is the count before paging.
 */
export function useAgentMessageThreads(skip = 0, limit = 50) {
  const tErrors = useTranslations("errors");
  const tAgentMessages = useTranslations("agentMessages");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.agentMessages.list(skip, limit),
    queryFn: () => listAgentMessageThreads(skip, limit),
  });

  return {
    threads: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error: error ? getErrorMessage(error, tErrors, tAgentMessages("failedLoad")) : null,
    refetch,
  };
}

/** One thread: its two agents, its last message, and whether it waits on the reader. */
export function useAgentMessageThread(threadId: string | null) {
  const tErrors = useTranslations("errors");
  const tAgentMessages = useTranslations("agentMessages");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.agentMessages.detail(threadId ?? ""),
    queryFn: () => getAgentMessageThread(threadId as string),
    enabled: threadId !== null,
  });

  return {
    thread: data ?? null,
    isLoading,
    error: error ? getErrorMessage(error, tErrors, tAgentMessages("failedLoad")) : null,
    refetch,
  };
}

/** One thread's messages, oldest first. */
export function useAgentMessages(threadId: string | null, skip = 0, limit = 50) {
  const tErrors = useTranslations("errors");
  const tAgentMessages = useTranslations("agentMessages");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.agentMessages.messages(threadId ?? ""),
    queryFn: () => listAgentMessages(threadId as string, skip, limit),
    enabled: threadId !== null,
  });

  return {
    messages: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error: error ? getErrorMessage(error, tErrors, tAgentMessages("failedLoad")) : null,
    refetch,
  };
}

/** The agents this caller may message, most recent first. */
export function useAgentMessageRecipients(skip = 0, limit = 100) {
  const tErrors = useTranslations("errors");
  const tAgentMessages = useTranslations("agentMessages");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.agentMessages.recipients(),
    queryFn: () => listAgentMessageRecipients(skip, limit),
  });

  return {
    recipients: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error: error ? getErrorMessage(error, tErrors, tAgentMessages("failedLoad")) : null,
    refetch,
  };
}

/**
 * Send a message as one agent to another. On success the thread list and
 * that thread's messages refresh; a refusal — the caller may not run one of
 * the two agents — is toasted with the backend's own words.
 */
export function useSendAgentMessage() {
  const t = useTranslations("agentMessages");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const send = useMutation({
    mutationFn: (input: AgentMessageSend) => sendAgentMessage(input),
    onSuccess: async (message) => {
      await queryClient.invalidateQueries({ queryKey: qk.agentMessages.list() });
      await queryClient.invalidateQueries({
        queryKey: qk.agentMessages.messages(message.thread_id),
      });
      toast.success(t("sent"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  return { send };
}

/** React to a message, or take the reaction back by sending it again. */
export function useReactToAgentMessage() {
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const react = useMutation({
    mutationFn: ({
      threadId,
      messageId,
      emoji,
      asAgentId,
    }: {
      threadId: string;
      messageId: string;
      emoji: string;
      asAgentId?: string | null;
    }) => reactToAgentMessage(threadId, messageId, emoji, asAgentId),
    onSuccess: async (_result, variables) => {
      await queryClient.invalidateQueries({
        queryKey: qk.agentMessages.messages(variables.threadId),
      });
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  return { react };
}

/** Mark a thread read, so its unread dot — and the widget's — goes away. */
export function useMarkAgentMessageThreadRead() {
  const queryClient = useQueryClient();

  const markRead = useMutation({
    mutationFn: (threadId: string) => markAgentMessageThreadRead(threadId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.agentMessages.list() });
    },
  });

  return { markRead };
}
