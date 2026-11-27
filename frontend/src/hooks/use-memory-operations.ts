"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getMemoryInboxDecisions,
  getMemoryInboxModelDecisions,
  getMemoryInboxRule,
  getMemoryObjectBackfill,
  getMemoryObjectMerges,
  getMemoryObjects,
  mergeMemoryObject,
  runMemoryObjectBackfill,
  setMemoryInboxRule,
  undoMemoryObjectMerge,
  type MemoryLibrary,
} from "@/lib/memory-api";
import { qk } from "@/lib/query-keys";

export function useMemoryObjectMerges(
  org: string,
  library: MemoryLibrary,
  id: string,
  aliasPage: string | null,
  q: string,
  candidatePage: string | null,
  canMerge: boolean,
) {
  const client = useQueryClient();
  const invalidate = () => client.invalidateQueries({ queryKey: qk.memory.all(org) });
  const aliases = useQuery({
    queryKey: qk.memory.objectAliases(org, library, id, aliasPage),
    queryFn: () => getMemoryObjectMerges(library, id, aliasPage),
  });
  const candidates = useQuery({
    queryKey: qk.memory.objectMergeCandidates(org, library, id, q, candidatePage),
    queryFn: () => getMemoryObjects(library, q, "all", candidatePage, id),
    enabled: canMerge,
  });
  const merge = useMutation({
    mutationFn: (source: string) => mergeMemoryObject(library, id, source),
    onSuccess: invalidate,
  });
  const undo = useMutation({
    mutationFn: (alias: string) => undoMemoryObjectMerge(library, id, alias),
    onSuccess: invalidate,
  });
  return { aliases, candidates, merge, undo };
}

export function useMemoryInboxRule(org: string) {
  const client = useQueryClient();
  const rule = useQuery({ queryKey: qk.memory.inboxRule(org), queryFn: getMemoryInboxRule });
  const save = useMutation({
    mutationFn: setMemoryInboxRule,
    onSuccess: (current) => client.setQueryData(qk.memory.inboxRule(org), current),
  });
  return { rule, save };
}

export function useMemoryInboxDecisions(org: string, version: number) {
  return useQuery({
    queryKey: qk.memory.inboxDecisions(org, version),
    queryFn: () => getMemoryInboxDecisions(version),
    enabled: version > 0,
  });
}

export function useMemoryInboxModelDecisions(org: string, version: number, enabled: boolean) {
  return useQuery({
    queryKey: qk.memory.inboxModelDecisions(org, version),
    queryFn: () => getMemoryInboxModelDecisions(version),
    enabled: enabled && version > 0,
  });
}

export function useMemoryObjectBackfill(org: string) {
  const client = useQueryClient();
  const backfill = useQuery({
    queryKey: qk.memory.objectBackfill(org),
    queryFn: getMemoryObjectBackfill,
    refetchInterval: ({ state }) => (state.data && !state.data.completed_at ? 5000 : false),
  });
  const run = useMutation({
    mutationFn: runMemoryObjectBackfill,
    onSuccess: (state) => client.setQueryData(qk.memory.objectBackfill(org), state),
  });
  return { backfill, run };
}
