"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { publishVisual, type VisualPublish } from "@/lib/visuals-api";

/**
 * Save a visual as an app. Refusals are the caller's to show: the dialog marks
 * the name a field-level refusal points at rather than toasting a sentence.
 */
export function usePublishVisual() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      conversationId,
      visualId,
      data,
    }: {
      conversationId: string;
      visualId: string;
      data: VisualPublish;
    }) => publishVisual(conversationId, visualId, data),
    // The apps list, and the visuals list whose rows say which one is saved.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.artifacts.all() }),
        queryClient.invalidateQueries({ queryKey: qk.visuals.all() }),
      ]),
  });
}
