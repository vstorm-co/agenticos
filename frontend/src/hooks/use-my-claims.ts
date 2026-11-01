"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import { correctClaim, getMyClaims, retractClaim, type MemoryClaimPage } from "@/lib/memory-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

interface UseMyClaimsResult {
  page: MemoryClaimPage | undefined;
  isLoading: boolean;
  error: unknown;
  history: boolean;
  setHistory: (history: boolean) => void;
  correct: (id: string, statement: string, effectiveFrom: string | null) => Promise<void>;
  retract: (id: string) => Promise<void>;
}

/**
 * What is recorded about the caller in the active organization.
 *
 * Keyed on the organization and on whether history is shown, like the notes: the
 * same person has a different record in each tenant. A correction that fails is
 * reported, never swallowed - somebody who corrected a wrong fact and sees nothing
 * happen would believe it was fixed.
 */
export function useMyClaims(): UseMyClaimsResult {
  const queryClient = useQueryClient();
  const t = useTranslations("errors");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const [history, setHistory] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: qk.memory.claims(activeOrgId ?? "current", history),
    queryFn: () => getMyClaims(history),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: qk.memory.all(activeOrgId ?? "current") });

  const correction = useMutation({
    mutationFn: (input: { id: string; statement: string; effectiveFrom: string | null }) =>
      correctClaim(input.id, input.statement, input.effectiveFrom),
    onSuccess: invalidate,
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });

  const retraction = useMutation({
    mutationFn: (id: string) => retractClaim(id),
    onSuccess: invalidate,
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });

  const correct = useCallback(
    async (id: string, statement: string, effectiveFrom: string | null) => {
      correction.mutate({ id, statement, effectiveFrom });
    },
    [correction],
  );

  const retract = useCallback(
    async (id: string) => {
      retraction.mutate(id);
    },
    [retraction],
  );

  return { page: data, isLoading, error, history, setHistory, correct, retract };
}
