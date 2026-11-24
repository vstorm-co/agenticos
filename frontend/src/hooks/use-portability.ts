"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  downloadAgentExport,
  listImportDestinations,
  type ImportDestinationQuery,
  importAgentBundle,
  previewAgentExport,
  previewAgentImport,
} from "@/lib/portability-api";
import { qk } from "@/lib/query-keys";

export function useAgentExport(id: string, enabled: boolean) {
  const preview = useQuery({
    queryKey: qk.agents.exportPreview(id),
    queryFn: () => previewAgentExport(id),
    enabled,
  });
  const download = useMutation({
    mutationFn: (data: { format: "yaml" | "json"; resources: Record<string, string[]> }) =>
      downloadAgentExport(id, data.format, data.resources),
  });
  return { preview, download };
}

export function useAgentImport() {
  const client = useQueryClient();
  const preview = useMutation({ mutationFn: previewAgentImport });
  const apply = useMutation({
    mutationFn: importAgentBundle,
    onSuccess: () => client.invalidateQueries({ queryKey: qk.agents.all() }),
  });
  return { preview, apply };
}

export function useImportDestinations(query: ImportDestinationQuery, enabled = true) {
  return useQuery({
    queryKey: qk.agents.importDestinations(query),
    queryFn: () => listImportDestinations(query),
    enabled,
  });
}
