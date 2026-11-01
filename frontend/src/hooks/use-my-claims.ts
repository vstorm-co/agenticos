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
  skip: number;
  showPage: (skip: number) => void;
  /** Resolves true once the correction is saved, false when it was refused. */
  correct: (id: string, statement: string, effectiveFrom: string | null) => Promise<boolean>;
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
  const [history, setHistoryState] = useState(false);
  const [skip, showPage] = useState(0);
  // The history is a different list, so the page does not carry over to it.
  const setHistory = useCallback((next: boolean) => {
    setHistoryState(next);
    showPage(0);
  }, []);

  const { data, isLoading, error } = useQuery({
    queryKey: qk.memory.claims(activeOrgId ?? "current", history, skip),
    queryFn: () => getMyClaims(history, skip),
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

  // Awaited, so the editor closes on a saved correction and stays open - with the
  // person's words in it - on a refused one. `onError` has already said why.
  const correct = useCallback(
    async (id: string, statement: string, effectiveFrom: string | null) => {
      try {
        await correction.mutateAsync({ id, statement, effectiveFrom });
        return true;
      } catch {
        return false;
      }
    },
    [correction],
  );

  const retract = useCallback(
    async (id: string) => {
      retraction.mutate(id);
    },
    [retraction],
  );

  return { page: data, isLoading, error, history, setHistory, skip, showPage, correct, retract };
}
