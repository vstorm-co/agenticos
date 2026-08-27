"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { rateMessage, removeRating } from "@/lib/message-rating-api";

import type { RatingValue } from "@/types/chat";

/**
 * Rating one assistant message, as mutations over the lib client.
 *
 * The chat's own thumb counts live in its message store, not a query, so the
 * caller still reconciles those; what goes through the query layer is the
 * invalidation of the ratings summaries the dashboard plots, so a rating cast in
 * chat is reflected there rather than left stale until the next mount.
 */
export function useMessageRating(conversationId: string, messageId: string) {
  const queryClient = useQueryClient();

  const invalidateSummaries = () => {
    // The roots of `qk.stats.ratings` (["ratings", "summary", …]) and
    // `qk.admin.ratings` (["admin", "ratings", …]) - both summary queries the
    // dashboard reads, matched by prefix.
    void queryClient.invalidateQueries({ queryKey: ["ratings"] });
    void queryClient.invalidateQueries({ queryKey: ["admin", "ratings"] });
  };

  const rate = useMutation({
    mutationFn: (body: { rating: RatingValue; comment: string | null }) =>
      rateMessage(conversationId, messageId, body),
    onSuccess: invalidateSummaries,
  });

  const remove = useMutation({
    mutationFn: () => removeRating(conversationId, messageId),
    onSuccess: invalidateSummaries,
  });

  return { rateMessage: rate.mutateAsync, removeRating: remove.mutateAsync };
}
