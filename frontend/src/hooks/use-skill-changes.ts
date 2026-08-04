"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import {
  applySkillChange,
  discardSkillChange,
  listSkillChanges,
  type ProposalStatus,
  type SkillChangeRecord,
} from "@/lib/skill-changes-api";

interface UseSkillChangesResult {
  changes: SkillChangeRecord[];
  isLoading: boolean;
  error: string | null;
  apply: (id: string) => Promise<void>;
  discard: (id: string) => Promise<void>;
  isDeciding: boolean;
}

/**
 * What agents proposed changing about this organization's skills.
 *
 * Both decisions invalidate the skills list as well as this one. Accepting a
 * change rewrites a skill and bumps its version, so a skills page left showing
 * the old body would be showing something no agent is following any more.
 */
export function useSkillChanges(status: ProposalStatus = "pending"): UseSkillChangesResult {
  const queryClient = useQueryClient();

  const {
    data: changes = [],
    isLoading,
    error: queryError,
  } = useQuery({
    queryKey: qk.skillChanges.list(status),
    queryFn: () => listSkillChanges(status),
  });

  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.skillChanges.all() }),
      queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
    ]);
  }, [queryClient]);

  const applied = useMutation({
    mutationFn: (id: string) => applySkillChange(id),
    onSuccess: async (change) => {
      await invalidate();
      toast.success(`Applied to ${change.name}`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const discarded = useMutation({
    mutationFn: (id: string) => discardSkillChange(id),
    onSuccess: async (change) => {
      await invalidate();
      toast.success(`Discarded the change to ${change.name}`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return {
    changes,
    isLoading,
    error:
      queryError instanceof Error
        ? queryError.message
        : queryError
          ? "Failed to load proposed skill changes"
          : null,
    apply: async (id: string) => {
      await applied.mutateAsync(id);
    },
    discard: async (id: string) => {
      await discarded.mutateAsync(id);
    },
    isDeciding: applied.isPending || discarded.isPending,
  };
}
