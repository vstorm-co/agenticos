/**
 * File upload API client for chat attachments.
 */

import { apiClient } from "./api-client";

export interface FileUploadResponse {
  id: string;
  filename: string;
  mime_type: string;
  size: number;
  file_type: string;
}

/**
 * Upload a chat attachment.
 *
 * Through `apiClient.upload` rather than a bare `fetch`: not for the
 * organization header - `/files` is scoped to the user, not the tenant - but
 * for the one-shot 401 refresh and a single `ApiError` shape. This had its own
 * copy of the error handling, which is one copy too many.
 */
export function uploadFile(file: File): Promise<FileUploadResponse> {
  return apiClient.upload<FileUploadResponse>("/files/upload", file);
}

export function getFileUrl(fileId: string): string {
  return `/api/files/${fileId}`;
}
