"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import {
  acceptSuggestion,
  dismissSuggestion,
  listSuggestions,
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
  const { data } = useQuery({
    queryKey: qk.suggestions.mine(),
    queryFn: listSuggestions,
  });
  const settle = { onSettled: () => client.invalidateQueries({ queryKey: qk.suggestions.mine() }) };
  const accept = useMutation({ mutationFn: (id: string) => acceptSuggestion(id), ...settle });
  const dismiss = useMutation({ mutationFn: (id: string) => dismissSuggestion(id), ...settle });

  return {
    suggestions: data ?? ([] as Suggestion[]),
    accept: accept.mutateAsync,
    dismiss: dismiss.mutateAsync,
  };
}
