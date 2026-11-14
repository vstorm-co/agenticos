"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  acceptSuggestion,
  dismissSuggestion,
  listPersonalStarters,
  listSuggestionHistory,
  listSuggestions,
  restoreSuggestion,
  type Suggestion,
} from "@/lib/suggestions-api";

/**
 * The person's open suggestions and their two answers (#2301).
 *
 * Read when the card that shows them mounts; made overnight, so there is nothing
 * to poll. Either answer removes the card at once - the list is invalidated, and
 * a declined one is never proposed again.
 */
export function useSuggestions(enabled = true) {
  const client = useQueryClient();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.suggestions.mine(),
    queryFn: listSuggestions,
    // The opening row reads ahead; mounting its card must not restart a failed read.
    retryOnMount: false,
    enabled,
  });
  const settle = {
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: qk.suggestions.mine() }),
        client.invalidateQueries({ queryKey: qk.outcomes.all() }),
        client.invalidateQueries({ queryKey: qk.durableTasks.root() }),
        client.invalidateQueries({ queryKey: qk.tables.all() }),
        client.invalidateQueries({ queryKey: qk.notifications.all() }),
        client.invalidateQueries({ queryKey: qk.watches.mine() }),
      ]),
  };
  const accept = useMutation({ mutationFn: (id: string) => acceptSuggestion(id), ...settle });
  const dismiss = useMutation({ mutationFn: (id: string) => dismissSuggestion(id), ...settle });

  return {
    suggestions: data ?? ([] as Suggestion[]),
    isLoading,
    error,
    refetch,
    accept: accept.mutateAsync,
    dismiss: dismiss.mutateAsync,
  };
}

/**
 * The first messages the nightly look wrote for the person in this organization
 * (#2301) - kept per membership, since they are drawn from this organization's
 * week. Mounted only where they are offered: the starter agent's empty chat.
 */
export function usePersonalStarterQuery(enabled = true) {
  return useQuery({
    queryKey: qk.suggestions.starters(),
    queryFn: listPersonalStarters,
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

/**
 * Every proposal the person was made, for Settings (#2301): what they took,
 * what they declined, and the way to bring a declined one back.
 */
export function useSuggestionHistory() {
  const client = useQueryClient();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.suggestions.history(),
    queryFn: listSuggestionHistory,
  });
  const restore = useMutation({
    mutationFn: (id: string) => restoreSuggestion(id),
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: qk.suggestions.mine() }),
        client.invalidateQueries({ queryKey: qk.outcomes.all() }),
        client.invalidateQueries({ queryKey: qk.durableTasks.root() }),
        client.invalidateQueries({ queryKey: qk.tables.all() }),
        client.invalidateQueries({ queryKey: qk.notifications.all() }),
        client.invalidateQueries({ queryKey: qk.watches.mine() }),
      ]),
  });
  return {
    history: data ?? ([] as Suggestion[]),
    isLoading,
    error,
    refetch,
    restore: restore.mutateAsync,
  };
}
