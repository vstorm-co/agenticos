import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";

export interface BundleReference {
  path: (string | number)[];
  target: string;
  is_key: boolean;
  destination_field: "id" | "version_number";
}

export interface BundleResource {
  key: string;
  kind: string;
  name: string;
  source_id: string | null;
  source_parent_id: string | null;
  source_version: string | null;
  definition: Record<string, unknown> | null;
  references: BundleReference[];
  included: string[];
}

export interface ResourceBundle {
  format: "agenticos.bundle";
  format_version: 1;
  roots: string[];
  resources: BundleResource[];
  assets: unknown[];
}

export interface BundlePreview {
  bundle: ResourceBundle;
  options: { key: string; available: boolean; can_create: boolean; reusable_id: string | null }[];
}

export interface ImportChoice {
  action: "create" | "reuse" | "skip";
  destination_id?: string | null;
  name?: string | null;
}

export interface ImportReceipt {
  roots: Record<string, string>;
  created: Record<string, string>;
  reused: Record<string, string>;
  skipped: string[];
}

export const previewAgentExport = (id: string) =>
  apiClient.get<BundlePreview>(`/agents/${id}/export-preview`);

export const previewAgentImport = (text: string) =>
  apiClient.post<BundlePreview>("/agents/import-preview", { text });

export const importAgentBundle = (data: {
  operation_id: string;
  bundle: ResourceBundle;
  choices: Record<string, ImportChoice>;
}) => apiClient.post<ImportReceipt>("/agents/import", data);

export async function downloadAgentExport(
  id: string,
  fileFormat: "yaml" | "json",
  resources: Record<string, string[]>,
): Promise<void> {
  const response = await apiClient.raw(`/agents/${id}/export`, {
    method: "POST",
    body: { file_format: fileFormat, resources },
  });
  saveBlob(await response.blob(), `agent-${id}.${fileFormat}`);
}
