"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/stores/auth-store";
import { qk } from "@/lib/query-keys";

export interface ConversationTask {
  id: string;
  source_conversation_id: string;
  conversation_id: string;
  agent_id: string;
  title: string;
  status:
    | "queued"
    | "running"
    | "awaiting_approval"
    | "awaiting_answer"
    | "completed"
    | "failed"
    | "cancelled"
    | "interrupted";
  delivery: "pending" | "running" | "delivered" | "interrupted" | "withdrawn";
  run_id: string | null;
  return_run_id: string | null;
  outcome: string | null;
  created_at: string;
}

export const taskIsActive = (task: ConversationTask) =>
  ["queued", "running", "awaiting_approval", "awaiting_answer"].includes(task.status);

/** Null lists the member's tasks for the dashboard; undefined is an unsent chat. */
export function useConversationTasks(conversationId: string | null | undefined) {
  const tenant = useTenantId();
  const guard = useTenantGuard();
  const userId = useAuthStore((state) => state.user?.id);
  const scope = `${userId ?? "-"}:${tenant ?? "-"}`;
  const client = useQueryClient();
  const tErrors = useTranslations("errors");
  const query = useQuery({
    queryKey: qk.conversationTasks.list(scope, conversationId),
    queryFn: ({ signal }) =>
      apiClient.get<ConversationTask[]>("/conversations/background-tasks", {
        signal,
        params: conversationId ? { conversation_id: conversationId } : {},
      }),
    enabled: !!tenant && !!userId && conversationId !== undefined,
    refetchInterval: (state) => (state.state.data?.some(taskIsActive) ? 3000 : 15000),
  });
  const stop = useMutation({
    mutationFn: (taskId: string) =>
      apiClient.post<ConversationTask>(
        `/conversations/background-tasks/${encodeURIComponent(taskId)}/stop`,
      ),
    onMutate: () => ({ tenant, userId }),
    onSuccess: (_data, _id, context) => {
      if (context && guard(context.tenant) && useAuthStore.getState().user?.id === context.userId)
        void client.invalidateQueries({ queryKey: qk.conversationTasks.all(scope) });
    },
    onError: (error, _id, context) => {
      if (context && guard(context.tenant) && useAuthStore.getState().user?.id === context.userId)
        toast.error(getErrorMessage(error, tErrors));
    },
  });
  return { ...query, stop };
}
