"use client";

import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import { readWikiWorkspace } from "@/lib/wiki-workspace";
import type { FileSource } from "@/lib/workspace-files";

/** Refetch contents too: several backends have no reliable per-file modification time. */
export function useWikiGraph(source: FileSource) {
  return useQuery({
    queryKey: qk.wikiGraph.source(source),
    queryFn: ({ signal }) => readWikiWorkspace(source, signal),
    refetchInterval: 30_000,
    refetchOnWindowFocus: "always",
    retry: false,
    gcTime: 0,
  });
}
