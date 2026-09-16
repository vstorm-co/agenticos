"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getRetention,
  putRetention,
  type RetentionDays,
  type RetentionPolicy,
} from "@/lib/retention-api";
import { qk } from "@/lib/query-keys";

interface UseRetentionResult {
  policy: RetentionPolicy | undefined;
  isLoading: boolean;
  isSaving: boolean;
  save: (days: RetentionDays) => Promise<void>;
}

/**
 * One organization's retention policy, read and written.
 *
 * Keyed on the organization in the URL rather than the active one: this page
 * names an organization in its path and *is* that organization, which is the
 * distinction #1032 was about.
 */
export function useRetention(orgId: string): UseRetentionResult {
  const queryClient = useQueryClient();
  const queryKey = qk.organizations.retention(orgId);

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => getRetention(orgId),
  });

  const mutation = useMutation({
    mutationFn: (days: RetentionDays) => putRetention(orgId, days),
    // The response is the whole resolved policy - what was asked for *and* what
    // the ceiling made of it - so writing it back is what shows a period being
    // cut rather than accepted.
    onSuccess: (policy) => queryClient.setQueryData<RetentionPolicy>(queryKey, policy),
  });

  const save = useCallback(
    async (days: RetentionDays) => {
      await mutation.mutateAsync(days);
    },
    [mutation],
  );

  return { policy: data, isLoading, isSaving: mutation.isPending, save };
}
