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
export function useSuggestions() {
  const client = useQueryClient();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.suggestions.mine(),
    queryFn: listSuggestions,
  });
  const settle = { onSettled: () => client.invalidateQueries({ queryKey: qk.suggestions.mine() }) };
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
export function usePersonalStarters(): string[] {
  const { data } = useQuery({ queryKey: qk.suggestions.starters(), queryFn: listPersonalStarters });
  return data ?? [];
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
    onSettled: () => client.invalidateQueries({ queryKey: qk.suggestions.mine() }),
  });
  return {
    history: data ?? ([] as Suggestion[]),
    isLoading,
    error,
    refetch,
    restore: restore.mutateAsync,
  };
}
