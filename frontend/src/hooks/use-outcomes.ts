"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listConversationOutcomes,
  settleOutcome,
  type Outcome,
  type OutcomeAction,
} from "@/lib/outcomes-api";
import { qk } from "@/lib/query-keys";

/**
 * What still needs the person in one chat (#2575): the card above the composer.
 *
 * Read when the chat opens and again when it regains focus - an outcome settled in
 * the Inbox or answered in another tab closes here without a push channel of its own.
 */
export function useConversationOutcomes(conversationId: string | null) {
  const { data } = useQuery({
    queryKey: qk.outcomes.conversation(conversationId ?? ""),
    queryFn: () => listConversationOutcomes(conversationId as string),
    enabled: conversationId !== null,
  });
  return (data ?? ([] as Outcome[])).filter((item) => item.status === "open");
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
        client.invalidateQueries({ queryKey: qk.notifications.all() }),
      ]),
  });
  return { settle: settle.mutateAsync, isPending: settle.isPending };
}
