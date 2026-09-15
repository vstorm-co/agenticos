"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteNote, getMyMemory, setNoteActive, type MemoryPage } from "@/lib/memory-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

interface UseMyMemoryResult {
  page: MemoryPage | undefined;
  isLoading: boolean;
  setActive: (id: string, active: boolean) => Promise<void>;
  remove: (id: string) => Promise<void>;
}

/**
 * What the agents in the active organization have written down about the caller.
 *
 * Keyed on the active organization because memory is per tenant: the same person
 * has a different store in each, and one cache entry for both would show Acme's
 * notes after switching to Globex.
 */
export function useMyMemory(): UseMyMemoryResult {
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const queryKey = qk.memory.mine(activeOrgId ?? "current");

  const { data, isLoading } = useQuery({ queryKey, queryFn: () => getMyMemory() });

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => setNoteActive(id, active),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const removal = useMutation({
    mutationFn: (id: string) => deleteNote(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const setActive = useCallback(
    async (id: string, active: boolean) => {
      await toggle.mutateAsync({ id, active });
    },
    [toggle],
  );

  const remove = useCallback(
    async (id: string) => {
      await removal.mutateAsync(id);
    },
    [removal],
  );

  return { page: data, isLoading, setActive, remove };
}
