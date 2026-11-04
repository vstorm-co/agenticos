"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { setPortalPollInterval } from "@/lib/org-mcp-connections-api";
import { qk } from "@/lib/query-keys";

/**
 * Change how often the organization's connected mailbox is checked.
 *
 * The interval rides on the portal catalog (`poll_interval_minutes`), so a
 * saved change refetches it for every card and trigger step showing the mailbox.
 */
export function usePortalPollInterval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ connectionId, minutes }: { connectionId: string; minutes: number }) =>
      setPortalPollInterval(connectionId, minutes),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.portals.catalog() }),
  });
}
