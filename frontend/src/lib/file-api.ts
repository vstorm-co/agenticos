/**
 * File upload API client for chat attachments.
 */

import { apiClient } from "./api-client";
import type { FileAccess } from "./file-access";
import { qk } from "./query-keys";

export interface FileUploadResponse {
  id: string;
  filename: string;
  mime_type: string;
  size: number;
  file_type: string;
  /**
   * The first few lines of the file's extracted text, or null for an image and
   * for anything no parser could read. The composer shows it on the attachment
   * card; the browser cannot derive it, since a PDF is bytes until the backend
   * has parsed it and the client holds only an id once the upload has answered.
   */
  preview: string | null;
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

/**
 * One chat attachment, as the shared viewer reads it.
 *
 * A same-origin route handler rather than `apiClient`, which is what lets a plain
 * `fetch` work here: `/files` is scoped to the user rather than the tenant, so there
 * is no organization header to lose. The session cookie is the whole of the
 * authorisation, hence `credentials: "include"`.
 *
 * `?disposition=attachment` on the download rather than saving bytes the preview
 * already holds: the route sets the header, and letting the browser follow a link is
 * one fewer copy of the file in memory.
 */
export function attachmentAccess(file: { id: string; filename: string }): FileAccess {
  const url = getFileUrl(file.id);
  const read = async () => {
    const response = await fetch(url, { credentials: "include" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response;
  };

  return {
    textKey: qk.attachments.text(file.id),
    bytesKey: qk.attachments.bytes(file.id),
    readText: async () => ({ content: await (await read()).text(), truncated: false }),
    readBytes: async () => (await read()).blob(),
    download: async () => {
      const link = document.createElement("a");
      link.href = `${url}?disposition=attachment`;
      link.download = file.filename;
      link.click();
    },
  };
}
