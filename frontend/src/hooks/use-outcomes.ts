"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { listConversationOutcomes, settleOutcome, type OutcomeAction } from "@/lib/outcomes-api";
import { qk } from "@/lib/query-keys";

/**
 * What still needs the person in one chat (#2575): the card above the composer.
 *
 * Read when the chat opens and again when it regains focus - an outcome settled in
 * the Inbox or answered in another tab closes here without a push channel of its own.
 */
export function useConversationOutcomes(conversationId: string | null) {
  const query = useQuery({
    queryKey: qk.outcomes.conversation(conversationId ?? ""),
    queryFn: () => listConversationOutcomes(conversationId as string),
    enabled: conversationId !== null,
  });
  return {
    outcomes: (query.data ?? []).filter((item) => item.status === "open"),
    error: query.error,
    retry: query.refetch,
  };
}

/**
 * Settle one outcome from wherever it is shown. Everything that shows it - these
 * cards and the bell's rows - is refreshed, because they are one outcome.
 */
export function useSettleOutcome(via: "inbox" | "chat") {
  const client = useQueryClient();
  const settle = useMutation({
    mutationFn: ({ id, action }: { id: string; action: OutcomeAction }) =>
      settleOutcome(id, action, via),
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: qk.outcomes.all() }),
        client.invalidateQueries({ queryKey: qk.durableTasks.root() }),
        client.invalidateQueries({ queryKey: qk.tables.all() }),
        client.invalidateQueries({ queryKey: qk.notifications.all() }),
        client.invalidateQueries({ queryKey: qk.suggestions.mine() }),
        client.invalidateQueries({ queryKey: qk.watches.mine() }),
      ]),
  });
  return { settle: settle.mutateAsync, isPending: settle.isPending };
}
