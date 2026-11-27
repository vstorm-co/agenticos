"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  downloadResourceExport,
  previewResourceExport,
  previewResourceImport,
  importResourceBundle,
  type BundleRootKind,
  type BundleImportRequest,
  listImportDestinations,
  type ImportDestinationQuery,
} from "@/lib/portability-api";
import { useAuthStore, useOrgStore } from "@/stores";
import { invalidateImportedResources } from "@/lib/bundle-cache";
import { qk } from "@/lib/query-keys";

export function useResourceExport(kind: BundleRootKind, id: string, enabled: boolean) {
  const user = useAuthStore((state) => state.user?.id ?? null);
  const org = useOrgStore((state) => state.activeOrgId);
  const preview = useQuery({
    queryKey: qk.portability.exportPreview(org, user, kind, id),
    queryFn: () => previewResourceExport(kind, id),
    enabled,
  });
  const download = useMutation({
    mutationFn: (data: { format: "yaml" | "json"; resources: Record<string, string[]> }) =>
      downloadResourceExport(kind, id, data.format, data.resources),
  });
  return { preview, download };
}

export function useResourceImport(kind: BundleRootKind) {
  const client = useQueryClient();
  const preview = useMutation({ mutationFn: (text: string) => previewResourceImport(kind, text) });
  const apply = useMutation({
    mutationFn: (data: BundleImportRequest) => importResourceBundle(kind, data),
    onSuccess: (receipt) => invalidateImportedResources(client, receipt),
  });
  return { preview, apply };
}

export function useImportDestinations(query: ImportDestinationQuery, enabled = true) {
  const user = useAuthStore((state) => state.user?.id ?? null);
  const org = useOrgStore((state) => state.activeOrgId);
  return useQuery({
    queryKey: qk.portability.destinations(org, user, query),
    queryFn: () => listImportDestinations(query),
    enabled,
  });
}
