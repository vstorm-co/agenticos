"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import { deleteNote, getMyMemory, setNoteActive, type MemoryPage } from "@/lib/memory-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

/** Notes per page. Enough that most people never see a second one. */
export const PAGE_SIZE = 50;

interface UseMyMemoryResult {
  page: MemoryPage | undefined;
  isLoading: boolean;
  /** The read failed after its retries. Distinct from `isLoading`, and from an empty store. */
  error: unknown;
  skip: number;
  showPage: (skip: number) => void;
  setActive: (id: string, active: boolean) => Promise<void>;
  remove: (id: string) => Promise<void>;
}

/**
 * What the agents in the active organization have written down about the caller.
 *
 * Keyed on the active organization because memory is per tenant: the same person
 * has a different store in each, and one cache entry for both would show Acme's
 * notes after switching to Globex. The page is part of the key too, so moving
 * between pages does not read one page's rows out of another's cache entry.
 *
 * Every mutation reports its own failure. A privacy action that fails silently
 * leaves somebody believing a note has stopped reaching the model when it has
 * not, which is the worst outcome this screen can produce (#1594 review).
 */
export function useMyMemory(): UseMyMemoryResult {
  const queryClient = useQueryClient();
  const t = useTranslations("errors");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const [skip, setSkip] = useState(0);
  const queryKey = qk.memory.mine(activeOrgId ?? "current", skip);

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () => getMyMemory(skip, PAGE_SIZE),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: qk.memory.all(activeOrgId ?? "current") });

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => setNoteActive(id, active),
    onSuccess: invalidate,
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });

  const removal = useMutation({
    mutationFn: (id: string) => deleteNote(id),
    onSuccess: invalidate,
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });

  // `mutate`, not `mutateAsync`: the click site has nothing to await and an
  // unawaited `mutateAsync` rejects into nobody's hands. `onError` reports.
  const setActive = useCallback(
    async (id: string, active: boolean) => {
      toggle.mutate({ id, active });
    },
    [toggle],
  );

  const remove = useCallback(
    async (id: string) => {
      removal.mutate(id);
    },
    [removal],
  );

  return { page: data, isLoading, error, skip, showPage: setSkip, setActive, remove };
}
