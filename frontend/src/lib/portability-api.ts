import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";

export type BundleRootKind = "agent" | "workflow";
export type BundlePath = (string | number)[];

export interface BundleReference {
  path: BundlePath;
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
  options: {
    key: string;
    available: boolean;
    can_create: boolean;
    reusable_id: string | null;
    layers?: string[];
    reusable_name?: string | null;
  }[];
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
  omitted_bindings?: Record<string, BundlePath[]>;
}

export const previewResourceExport = (kind: BundleRootKind, id: string) =>
  apiClient.get<BundlePreview>(
    `/${kind === "agent" ? "agents" : "workflows"}/${id}/export-preview`,
  );

export const previewResourceImport = (kind: BundleRootKind, text: string) =>
  apiClient.post<BundlePreview>(
    kind === "agent" ? "/agents/import-preview" : "/workflows/bundle-import-preview",
    { text },
  );

export interface BundleImportRequest {
  operation_id: string;
  bundle: ResourceBundle;
  choices: Record<string, ImportChoice>;
}

export const importResourceBundle = (kind: BundleRootKind, data: BundleImportRequest) =>
  apiClient.post<ImportReceipt>(
    kind === "agent" ? "/agents/import" : "/workflows/bundle-import",
    data,
  );

export async function downloadResourceExport(
  kind: BundleRootKind,
  id: string,
  fileFormat: "yaml" | "json",
  resources: Record<string, string[]>,
): Promise<void> {
  const path = kind === "agent" ? `/agents/${id}/export` : `/workflows/${id}/bundle-export`;
  const response = await apiClient.raw(path, {
    method: "POST",
    body: { file_format: fileFormat, resources },
  });
  saveBlob(await response.blob(), `${kind}-${id}.${fileFormat}`);
}

export interface ImportDestinationQuery {
  kind: string;
  parent_id?: string;
  search: string;
  skip: number;
  limit: number;
}

export interface ImportDestinationList {
  items: { id: string; name: string }[];
  total: number;
  searchable: boolean;
}

export const listImportDestinations = (query: ImportDestinationQuery) => {
  const params = new URLSearchParams({
    kind: query.kind,
    search: query.search,
    skip: String(query.skip),
    limit: String(query.limit),
  });
  if (query.parent_id) params.set("parent_id", query.parent_id);
  return apiClient.get<ImportDestinationList>(`/agents/import-destinations?${params}`);
};

export interface TransferOperation {
  id: string;
  request_id: string;
  direction: "export" | "import";
  phase: "prepare" | "apply";
  status:
    | "awaiting_upload"
    | "queued"
    | "running"
    | "review"
    | "needs_bindings"
    | "ready"
    | "failed"
    | "expired";
  revision: number;
  completed_bytes: number;
  total_bytes: number;
  expires_at: string;
  error_code: string | null;
  preview: BundlePreview | null;
  receipt: ImportReceipt | null;
  can_download: boolean;
}

export const startBundleExport = (
  rootId: string,
  resources: Record<string, string[]>,
  requestId: string,
  rootKind: BundleRootKind = "agent",
) =>
  apiClient.post<TransferOperation>("/portability/exports", {
    request_id: requestId,
    root_kind: rootKind,
    root_id: rootId,
    resources,
  });

export const startBundleUpload = (file: File, requestId: string) =>
  apiClient.post<TransferOperation>("/portability/uploads", {
    request_id: requestId,
    filename: file.name,
    size_bytes: file.size,
  });

export const uploadBundleFile = (id: string, file: File) =>
  apiClient.put<TransferOperation>(`/portability/${id}/upload`, file);

export const getBundleTransfer = (id: string, signal?: AbortSignal) =>
  apiClient.get<TransferOperation>(`/portability/${id}`, { signal });

export const applyBundleTransfer = (
  id: string,
  revision: number,
  choices: Record<string, ImportChoice>,
) =>
  apiClient.post<TransferOperation>(`/portability/${id}/apply`, {
    expected_revision: revision,
    choices,
  });

export async function downloadBundleTransfer(id: string): Promise<void> {
  const response = await apiClient.raw(`/portability/${id}/download`, { method: "GET" });
  saveBlob(await response.blob(), `agenticos-${id}.zip`);
}
