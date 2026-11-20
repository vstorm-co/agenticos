"use client";

import { useQuery } from "@tanstack/react-query";

import { listDriveFolders } from "@/lib/rag-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

/** One level of a connected Google account's Drive; see `listDriveFolders` for `parent`. */
export function useDriveFolders(account: string, parent: string) {
  const orgId = useOrgStore((state) => state.activeOrgId);
  return useQuery({
    queryKey: qk.rag.driveFolders(orgId, account, parent),
    queryFn: () => listDriveFolders(account, parent),
  });
}
