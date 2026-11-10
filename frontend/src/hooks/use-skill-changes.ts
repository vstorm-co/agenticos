"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
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
  apply: (change: SkillChangeRecord) => Promise<void>;
  discard: (change: SkillChangeRecord) => Promise<void>;
  isDeciding: boolean;
}

/**
 * What agents proposed changing about this organization's skills.
 *
 * Both decisions invalidate the skills list as well as this one. Accepting a
 * change rewrites a skill and bumps its version, so a skills page left showing
 * the old body would be showing something no agent is following any more.
 * A refused decision reads them again too - a proposal a newer run rewrote
 * comes back at its new revision.
 */
export function useSkillChanges(status: ProposalStatus = "pending"): UseSkillChangesResult {
  const tErrors = useTranslations("errors");
  const t = useTranslations("skills");
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
    mutationFn: (change: SkillChangeRecord) => applySkillChange(change),
    onSuccess: async (change) => {
      await invalidate();
      toast.success(t("changeApplied", { name: change.name }));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, tErrors));
      void invalidate();
    },
  });

  const discarded = useMutation({
    mutationFn: (change: SkillChangeRecord) => discardSkillChange(change),
    onSuccess: async (change) => {
      await invalidate();
      toast.success(t("changeDiscarded", { name: change.name }));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, tErrors));
      void invalidate();
    },
  });

  return {
    changes,
    isLoading,
    error: queryError ? getErrorMessage(queryError, tErrors, t("failedLoadProposedChanges")) : null,
    apply: async (change: SkillChangeRecord) => {
      await applied.mutateAsync(change);
    },
    discard: async (change: SkillChangeRecord) => {
      await discarded.mutateAsync(change);
    },
    isDeciding: applied.isPending || discarded.isPending,
  };
}
